package dev.saseq.services;

import net.dv8tion.jda.api.Permission;
import net.dv8tion.jda.api.entities.Member;
import net.dv8tion.jda.api.entities.channel.ChannelType;
import net.dv8tion.jda.api.entities.channel.concrete.ForumChannel;
import net.dv8tion.jda.api.entities.channel.forums.ForumTag;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import net.dv8tion.jda.api.interactions.commands.OptionType;
import net.dv8tion.jda.api.interactions.commands.build.CommandData;
import net.dv8tion.jda.api.interactions.commands.build.Commands;
import net.dv8tion.jda.api.interactions.commands.build.OptionData;
import net.dv8tion.jda.api.utils.messages.MessageCreateData;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.text.DecimalFormat;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

@Service
public class PrimoSlashCommandService extends ListenerAdapter {

    private static final String COMMAND_VAT = "vat";
    private static final String COMMAND_ORDER = "order";

    private static final String ORDER_FORUM_OPTION = "forum";
    private static final String ORDER_TAGS_OPTION = "tags";
    private static final String ORDER_MESSAGE_OPTION = "message";

    private static final BigDecimal ONE_HUNDRED = BigDecimal.valueOf(100);
    private static final BigDecimal FIXED_VAT_RATE = BigDecimal.valueOf(12);
    private static final MathContext MC = MathContext.DECIMAL64;

    private static final DateTimeFormatter ORDER_TITLE_FORMAT = DateTimeFormatter.ofPattern("MMMM d - EEEE", Locale.ENGLISH);
    private static final int MAX_FORUM_TAGS_PER_POST = 5;
    private static final int DISCORD_MESSAGE_MAX_LENGTH = 2000;

    public static CommandData buildVatSlashCommand() {
        return Commands.slash(COMMAND_VAT, "Calculate VAT totals for POS or invoices")
                .addOptions(
                        new OptionData(OptionType.NUMBER, "amount", "Amount to calculate from", true),
                        new OptionData(OptionType.STRING, "basis", "Select whether the amount is VAT Inclusive or VAT Exclusive", true)
                                .addChoice("VAT Inclusive", "inclusive")
                                .addChoice("VAT Exclusive", "exclusive")
                );
    }

    public static CommandData buildOrderSlashCommand() {
        return Commands.slash(COMMAND_ORDER, "Create a forum order post in one command")
                .addOptions(
                        new OptionData(OptionType.CHANNEL, ORDER_FORUM_OPTION, "Forum channel to post in", true)
                                .setChannelTypes(ChannelType.FORUM),
                        new OptionData(OptionType.STRING, ORDER_MESSAGE_OPTION, "Order body content", true),
                        new OptionData(OptionType.STRING, ORDER_TAGS_OPTION, "Comma-separated tags (example: urgent, delivery)", false)
                );
    }

    @Override
    public void onSlashCommandInteraction(SlashCommandInteractionEvent event) {
        if (COMMAND_VAT.equals(event.getName())) {
            handleVat(event);
            return;
        }
        if (COMMAND_ORDER.equals(event.getName())) {
            handleOrder(event);
            return;
        }
    }

    private void handleVat(SlashCommandInteractionEvent event) {
        var amountOption = event.getOption("amount");
        var basisOption = event.getOption("basis");

        if (amountOption == null || basisOption == null) {
            event.reply("Missing required options. Use `/vat amount:<number> basis:<inclusive|exclusive>`.").setEphemeral(true).queue();
            return;
        }

        BigDecimal amount = BigDecimal.valueOf(amountOption.getAsDouble());
        String basis = basisOption.getAsString();

        if (amount.compareTo(BigDecimal.ZERO) < 0) {
            event.reply("Amount must be zero or greater.").setEphemeral(true).queue();
            return;
        }

        VatResult result = calculateVat(amount, FIXED_VAT_RATE, basis);

        String response = """
                **Primo VAT Calculator**
                Basis: %s
                Rate: %s%% (fixed)
                Net (VAT Exclusive): %s
                VAT: %s
                Gross (VAT Inclusive): %s
                """.formatted(
                result.basisLabel,
                formatNumber(FIXED_VAT_RATE),
                formatMoney(result.netAmount),
                formatMoney(result.vatAmount),
                formatMoney(result.grossAmount)
        );

        event.reply(response).queue();
    }

    private void handleOrder(SlashCommandInteractionEvent event) {
        var guild = event.getGuild();
        var member = event.getMember();
        if (guild == null || member == null) {
            event.reply("This command can only be used inside a Discord server.").setEphemeral(true).queue();
            return;
        }

        var forumOption = event.getOption(ORDER_FORUM_OPTION);
        var messageOption = event.getOption(ORDER_MESSAGE_OPTION);
        var tagsOption = event.getOption(ORDER_TAGS_OPTION);

        if (forumOption == null || messageOption == null) {
            event.reply("Missing required options. Use `/order forum:<forum> tags:<tag1, tag2> message:<order text>`.")
                    .setEphemeral(true)
                    .queue();
            return;
        }

        if (!(forumOption.getAsChannel() instanceof ForumChannel forum)) {
            event.reply("Please select a valid forum channel in the `forum` option.").setEphemeral(true).queue();
            return;
        }

        if (!canMemberCreateForumPost(member, forum)) {
            event.reply("You do not have permission to create posts in %s.".formatted(forum.getAsMention()))
                    .setEphemeral(true)
                    .queue();
            return;
        }

        String orderMessage = messageOption.getAsString().trim();
        if (orderMessage.isBlank()) {
            event.reply("`message` cannot be empty.").setEphemeral(true).queue();
            return;
        }
        String postBody = member.getAsMention() + "\n" + orderMessage;
        if (postBody.length() > DISCORD_MESSAGE_MAX_LENGTH) {
            event.reply("`message` is too long after adding your @mention. Discord allows up to %d characters."
                            .formatted(DISCORD_MESSAGE_MAX_LENGTH))
                    .setEphemeral(true)
                    .queue();
            return;
        }

        String tagsRaw = tagsOption != null ? tagsOption.getAsString() : "";
        List<ForumTag> selectedTags = resolveForumTags(forum, tagsRaw);
        if (selectedTags == null) {
            event.reply(buildTagUsageError(forum, tagsRaw)).setEphemeral(true).queue();
            return;
        }

        String postTitle = LocalDate.now().format(ORDER_TITLE_FORMAT);
        var action = forum.createForumPost(postTitle, MessageCreateData.fromContent(postBody));
        if (!selectedTags.isEmpty()) {
            action = action.setTags(selectedTags);
        }

        action.queue(
                forumPost -> event.reply("All set. Your order has been posted in %s with the title **%s**: %s."
                                .formatted(forum.getAsMention(), postTitle, forumPost.getThreadChannel().getAsMention()))
                        .setEphemeral(true)
                        .queue(),
                failure -> event.reply("Failed to create forum post: " + failure.getMessage())
                        .setEphemeral(true)
                        .queue()
        );
    }

    private List<ForumTag> resolveForumTags(ForumChannel forum, String tagsRaw) {
        List<ForumTag> availableTags = forum.getAvailableTags();
        if (availableTags.isEmpty()) {
            return tagsRaw == null || tagsRaw.isBlank() ? List.of() : null;
        }

        List<String> requestedTokens = parseTagTokens(tagsRaw);
        if (requestedTokens.isEmpty() || requestedTokens.size() > MAX_FORUM_TAGS_PER_POST) {
            return null;
        }

        Map<String, ForumTag> byId = availableTags.stream()
                .collect(Collectors.toMap(ForumTag::getId, tag -> tag));

        Map<String, ForumTag> byLowerName = new LinkedHashMap<>();
        for (ForumTag tag : availableTags) {
            byLowerName.putIfAbsent(tag.getName().toLowerCase(Locale.ENGLISH), tag);
        }

        Set<String> selectedIds = new LinkedHashSet<>();
        for (String token : requestedTokens) {
            ForumTag byExactId = byId.get(token);
            if (byExactId != null) {
                selectedIds.add(byExactId.getId());
                continue;
            }

            ForumTag byName = byLowerName.get(token.toLowerCase(Locale.ENGLISH));
            if (byName == null) {
                return null;
            }
            selectedIds.add(byName.getId());
        }

        if (selectedIds.isEmpty()) {
            return null;
        }

        return availableTags.stream()
                .filter(tag -> selectedIds.contains(tag.getId()))
                .toList();
    }

    private List<String> parseTagTokens(String tagsRaw) {
        if (tagsRaw == null || tagsRaw.isBlank()) {
            return List.of();
        }

        List<String> tokens = new ArrayList<>();
        for (String piece : tagsRaw.split(",")) {
            String token = piece.trim();
            if (!token.isEmpty()) {
                tokens.add(token);
            }
        }
        return tokens;
    }

    private String buildTagUsageError(ForumChannel forum, String tagsRaw) {
        List<ForumTag> availableTags = forum.getAvailableTags();
        if (availableTags.isEmpty()) {
            return "This forum does not have tags. Leave `tags` empty when using `/order`.";
        }

        String availableTagNames = availableTags.stream()
                .map(ForumTag::getName)
                .collect(Collectors.joining(", "));

        if (tagsRaw == null || tagsRaw.isBlank()) {
            return "Please provide 1 to %d tags in `tags` (comma-separated). Available tags in %s: %s"
                    .formatted(MAX_FORUM_TAGS_PER_POST, forum.getAsMention(), availableTagNames);
        }

        return "Invalid `tags` value. Use comma-separated tag names or tag IDs (max %d). Available tags in %s: %s"
                .formatted(MAX_FORUM_TAGS_PER_POST, forum.getAsMention(), availableTagNames);
    }

    private boolean canMemberCreateForumPost(Member member, ForumChannel channel) {
        if (member == null) {
            return false;
        }
        boolean hasVisibility = member.hasPermission(channel, Permission.VIEW_CHANNEL);
        boolean canSend = member.hasPermission(channel, Permission.MESSAGE_SEND);
        return hasVisibility && canSend;
    }

    private VatResult calculateVat(BigDecimal amount, BigDecimal vatRatePercent, String basis) {
        BigDecimal rateFraction = vatRatePercent.divide(ONE_HUNDRED, MC);
        BigDecimal net;
        BigDecimal vat;
        BigDecimal gross;
        String basisLabel;

        if ("inclusive".equalsIgnoreCase(basis) || "gross".equalsIgnoreCase(basis)) {
            gross = amount;
            BigDecimal divisor = BigDecimal.ONE.add(rateFraction, MC);
            net = gross.divide(divisor, MC);
            vat = gross.subtract(net, MC);
            basisLabel = "Gross (VAT Inclusive)";
        } else if ("exclusive".equalsIgnoreCase(basis) || "net".equalsIgnoreCase(basis)) {
            net = amount;
            vat = net.multiply(rateFraction, MC);
            gross = net.add(vat, MC);
            basisLabel = "Net (VAT Exclusive)";
        } else {
            throw new IllegalArgumentException("basis must be either 'inclusive' or 'exclusive'");
        }

        return new VatResult(
                basisLabel,
                roundMoney(net),
                roundMoney(vat),
                roundMoney(gross)
        );
    }

    private BigDecimal roundMoney(BigDecimal value) {
        return value.setScale(2, RoundingMode.HALF_UP);
    }

    private String formatMoney(BigDecimal value) {
        return "PHP " + formatNumber(value);
    }

    private String formatNumber(BigDecimal value) {
        DecimalFormat format = new DecimalFormat("#,##0.00");
        return format.format(value);
    }

    private record VatResult(
            String basisLabel,
            BigDecimal netAmount,
            BigDecimal vatAmount,
            BigDecimal grossAmount
    ) {
    }
}
