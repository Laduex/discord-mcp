package dev.saseq.services;

import net.dv8tion.jda.api.Permission;
import net.dv8tion.jda.api.entities.Member;
import net.dv8tion.jda.api.entities.channel.concrete.ForumChannel;
import net.dv8tion.jda.api.entities.channel.forums.ForumTag;
import net.dv8tion.jda.api.events.interaction.ModalInteractionEvent;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import net.dv8tion.jda.api.events.interaction.component.StringSelectInteractionEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import net.dv8tion.jda.api.interactions.commands.OptionType;
import net.dv8tion.jda.api.interactions.commands.build.CommandData;
import net.dv8tion.jda.api.interactions.commands.build.Commands;
import net.dv8tion.jda.api.interactions.commands.build.OptionData;
import net.dv8tion.jda.api.interactions.commands.build.SubcommandData;
import net.dv8tion.jda.api.interactions.components.selections.StringSelectMenu;
import net.dv8tion.jda.api.interactions.components.text.TextInput;
import net.dv8tion.jda.api.interactions.components.text.TextInputStyle;
import net.dv8tion.jda.api.interactions.modals.Modal;
import net.dv8tion.jda.api.utils.messages.MessageCreateData;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.text.DecimalFormat;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class PrimoSlashCommandService extends ListenerAdapter {

    private static final String COMMAND_NAME = "primo";
    private static final String SUBCOMMAND_VAT = "vat";
    private static final String SUBCOMMAND_ORDER = "order";

    private static final BigDecimal ONE_HUNDRED = BigDecimal.valueOf(100);
    private static final BigDecimal FIXED_VAT_RATE = BigDecimal.valueOf(12);
    private static final MathContext MC = MathContext.DECIMAL64;

    private static final DateTimeFormatter ORDER_TITLE_FORMAT = DateTimeFormatter.ofPattern("MMMM d - EEEE", Locale.ENGLISH);
    private static final Duration ORDER_SESSION_TTL = Duration.ofMinutes(15);
    private static final int MAX_SELECT_OPTIONS = 25;
    private static final int MAX_FORUM_TAGS_PER_POST = 5;

    private static final String FORUM_SELECT_ID_PREFIX = "primo-order-forum:";
    private static final String TAG_SELECT_ID_PREFIX = "primo-order-tags:";
    private static final String BODY_MODAL_ID_PREFIX = "primo-order-body:";
    private static final String ORDER_BODY_INPUT_ID = "order_body";

    private final Map<String, PendingOrderSession> orderSessions = new ConcurrentHashMap<>();

    public static CommandData buildPrimoSlashCommand() {
        var vatSubcommand = new SubcommandData(SUBCOMMAND_VAT, "Calculate VAT totals for POS or invoices")
                .addOptions(
                        new OptionData(OptionType.NUMBER, "amount", "Amount to calculate from", true),
                        new OptionData(OptionType.STRING, "basis", "Select whether the amount is VAT Inclusive or VAT Exclusive", true)
                                .addChoice("VAT Inclusive", "inclusive")
                                .addChoice("VAT Exclusive", "exclusive")
                );

        var orderSubcommand = new SubcommandData(SUBCOMMAND_ORDER, "Create a forum order post using a guided flow");

        return Commands.slash(COMMAND_NAME, "Primo utility commands")
                .addSubcommands(vatSubcommand, orderSubcommand);
    }

    @Override
    public void onSlashCommandInteraction(SlashCommandInteractionEvent event) {
        if (!COMMAND_NAME.equals(event.getName())) {
            return;
        }

        var subcommand = event.getSubcommandName();
        if (SUBCOMMAND_VAT.equals(subcommand)) {
            handleVat(event);
            return;
        }
        if (SUBCOMMAND_ORDER.equals(subcommand)) {
            handleOrderStart(event);
            return;
        }

        event.reply("Unknown subcommand. Use `/primo vat` or `/primo order`.").setEphemeral(true).queue();
    }

    @Override
    public void onStringSelectInteraction(StringSelectInteractionEvent event) {
        String componentId = event.getComponentId();
        if (componentId.startsWith(FORUM_SELECT_ID_PREFIX)) {
            handleForumSelection(event, extractSessionId(componentId, FORUM_SELECT_ID_PREFIX));
            return;
        }
        if (componentId.startsWith(TAG_SELECT_ID_PREFIX)) {
            handleTagSelection(event, extractSessionId(componentId, TAG_SELECT_ID_PREFIX));
        }
    }

    @Override
    public void onModalInteraction(ModalInteractionEvent event) {
        String modalId = event.getModalId();
        if (!modalId.startsWith(BODY_MODAL_ID_PREFIX)) {
            return;
        }
        handleOrderBodySubmission(event, extractSessionId(modalId, BODY_MODAL_ID_PREFIX));
    }

    private void handleVat(SlashCommandInteractionEvent event) {
        var amountOption = event.getOption("amount");
        var basisOption = event.getOption("basis");

        if (amountOption == null || basisOption == null) {
            event.reply("Missing required options. Use `/primo vat amount:<number> basis:<inclusive|exclusive>`.").setEphemeral(true).queue();
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

    private void handleOrderStart(SlashCommandInteractionEvent event) {
        cleanupExpiredOrderSessions();

        var guild = event.getGuild();
        var member = event.getMember();
        if (guild == null || member == null) {
            event.reply("This command can only be used inside a Discord server.").setEphemeral(true).queue();
            return;
        }

        List<ForumChannel> availableForums = guild.getForumChannels().stream()
                .filter(channel -> canMemberCreateForumPost(member, channel))
                .sorted(Comparator.comparing(ForumChannel::getName))
                .toList();

        if (availableForums.isEmpty()) {
            event.reply("No forum channels are available for your current role permissions.").setEphemeral(true).queue();
            return;
        }

        String sessionId = createOrderSession(member.getIdLong(), guild.getIdLong());

        var menuBuilder = StringSelectMenu.create(FORUM_SELECT_ID_PREFIX + sessionId)
                .setPlaceholder("Choose a forum")
                .setRequiredRange(1, 1);

        availableForums.stream()
                .limit(MAX_SELECT_OPTIONS)
                .forEach(forum -> menuBuilder.addOption(forum.getName(), forum.getId(), forum.getAsMention()));

        StringBuilder response = new StringBuilder("Where would you like to post your order?");
        if (availableForums.size() > MAX_SELECT_OPTIONS) {
            response.append("\nShowing the first ").append(MAX_SELECT_OPTIONS).append(" forums by name.");
        }

        event.reply(response.toString())
                .setEphemeral(true)
                .addActionRow(menuBuilder.build())
                .queue();
    }

    private void handleForumSelection(StringSelectInteractionEvent event, String sessionId) {
        PendingOrderSession session = validateOrderSession(event, sessionId);
        if (session == null) {
            return;
        }

        var guild = event.getGuild();
        if (guild == null) {
            event.reply("This interaction must be used inside a Discord server.").setEphemeral(true).queue();
            return;
        }

        String forumId = event.getValues().get(0);
        ForumChannel forum = guild.getForumChannelById(forumId);
        if (forum == null) {
            event.reply("That forum no longer exists. Start again with `/primo order`.").setEphemeral(true).queue();
            orderSessions.remove(sessionId);
            return;
        }

        if (!canMemberCreateForumPost(event.getMember(), forum)) {
            event.reply("You no longer have permission to create posts in that forum.").setEphemeral(true).queue();
            orderSessions.remove(sessionId);
            return;
        }

        session.forumId = forumId;
        List<ForumTag> tags = forum.getAvailableTags();

        if (tags.isEmpty()) {
            event.replyModal(buildOrderBodyModal(sessionId)).queue();
            return;
        }

        int minTags = 1;
        int maxTags = Math.min(Math.min(tags.size(), MAX_FORUM_TAGS_PER_POST), MAX_SELECT_OPTIONS);

        var menuBuilder = StringSelectMenu.create(TAG_SELECT_ID_PREFIX + sessionId)
                .setPlaceholder("Select one or more tags")
                .setRequiredRange(minTags, maxTags);

        tags.stream()
                .limit(MAX_SELECT_OPTIONS)
                .forEach(tag -> menuBuilder.addOption(tag.getName(), tag.getId()));

        event.reply("Choose up to %d tags for **%s**, then submit."
                        .formatted(MAX_FORUM_TAGS_PER_POST, forum.getName()))
                .setEphemeral(true)
                .addActionRow(menuBuilder.build())
                .queue();
    }

    private void handleTagSelection(StringSelectInteractionEvent event, String sessionId) {
        PendingOrderSession session = validateOrderSession(event, sessionId);
        if (session == null) {
            return;
        }

        session.selectedTagIds = new ArrayList<>(event.getValues());
        event.replyModal(buildOrderBodyModal(sessionId)).queue();
    }

    private void handleOrderBodySubmission(ModalInteractionEvent event, String sessionId) {
        PendingOrderSession session = validateOrderSession(event, sessionId);
        if (session == null) {
            return;
        }

        var guild = event.getGuild();
        if (guild == null) {
            event.reply("This interaction must be used inside a Discord server.").setEphemeral(true).queue();
            orderSessions.remove(sessionId);
            return;
        }

        String body = event.getValue(ORDER_BODY_INPUT_ID) != null
                ? event.getValue(ORDER_BODY_INPUT_ID).getAsString()
                : "";
        if (body.isBlank()) {
            event.reply("Order body cannot be empty. Start again with `/primo order`.").setEphemeral(true).queue();
            return;
        }

        if (session.forumId == null || session.forumId.isBlank()) {
            event.reply("Forum selection is missing. Start again with `/primo order`.").setEphemeral(true).queue();
            orderSessions.remove(sessionId);
            return;
        }

        ForumChannel forum = guild.getForumChannelById(session.forumId);
        if (forum == null) {
            event.reply("The selected forum no longer exists. Start again with `/primo order`.").setEphemeral(true).queue();
            orderSessions.remove(sessionId);
            return;
        }

        if (!canMemberCreateForumPost(event.getMember(), forum)) {
            event.reply("You no longer have permission to create posts in that forum.").setEphemeral(true).queue();
            orderSessions.remove(sessionId);
            return;
        }

        List<ForumTag> availableTags = forum.getAvailableTags();
        Set<String> selectedTagIdSet = new HashSet<>(session.selectedTagIds);
        List<ForumTag> selectedTags = availableTags.stream()
                .filter(tag -> selectedTagIdSet.contains(tag.getId()))
                .limit(MAX_FORUM_TAGS_PER_POST)
                .toList();

        if (!availableTags.isEmpty() && selectedTags.isEmpty()) {
            event.reply("Please select at least one tag. Start again with `/primo order`.").setEphemeral(true).queue();
            return;
        }

        String postTitle = LocalDate.now().format(ORDER_TITLE_FORMAT);

        var action = forum.createForumPost(postTitle, MessageCreateData.fromContent(body));
        if (!selectedTags.isEmpty()) {
            action = action.setTags(selectedTags);
        }

        action.queue(
                forumPost -> {
                    orderSessions.remove(sessionId);
                    event.reply("All set. Your order has been posted in %s with the title **%s**: %s."
                                    .formatted(forum.getAsMention(), postTitle, forumPost.getThreadChannel().getAsMention()))
                            .setEphemeral(true)
                            .queue();
                },
                failure -> event.reply("Failed to create forum post: " + failure.getMessage())
                        .setEphemeral(true)
                        .queue()
        );
    }

    private String createOrderSession(long userId, long guildId) {
        String sessionId = UUID.randomUUID().toString().replace("-", "");
        orderSessions.put(sessionId, new PendingOrderSession(
                userId,
                guildId,
                Instant.now().plus(ORDER_SESSION_TTL),
                null,
                new ArrayList<>()
        ));
        return sessionId;
    }

    private PendingOrderSession validateOrderSession(StringSelectInteractionEvent event, String sessionId) {
        PendingOrderSession session = getOrderSession(sessionId);
        if (session == null) {
            event.reply("Session expired. Please run `/primo order` again.").setEphemeral(true).queue();
            return null;
        }
        if (event.getUser().getIdLong() != session.userId) {
            event.reply("Only the command author can use this menu.").setEphemeral(true).queue();
            return null;
        }
        if (event.getGuild() == null || event.getGuild().getIdLong() != session.guildId) {
            event.reply("This menu is no longer valid in this server.").setEphemeral(true).queue();
            return null;
        }
        return session;
    }

    private PendingOrderSession validateOrderSession(ModalInteractionEvent event, String sessionId) {
        PendingOrderSession session = getOrderSession(sessionId);
        if (session == null) {
            event.reply("Session expired. Please run `/primo order` again.").setEphemeral(true).queue();
            return null;
        }
        if (event.getUser().getIdLong() != session.userId) {
            event.reply("Only the command author can submit this form.").setEphemeral(true).queue();
            return null;
        }
        if (event.getGuild() == null || event.getGuild().getIdLong() != session.guildId) {
            event.reply("This form is no longer valid in this server.").setEphemeral(true).queue();
            return null;
        }
        return session;
    }

    private PendingOrderSession getOrderSession(String sessionId) {
        cleanupExpiredOrderSessions();
        return orderSessions.get(sessionId);
    }

    private void cleanupExpiredOrderSessions() {
        Instant now = Instant.now();
        orderSessions.entrySet().removeIf(entry -> entry.getValue().expiresAt.isBefore(now));
    }

    private String extractSessionId(String interactionId, String prefix) {
        return interactionId.substring(prefix.length());
    }

    private Modal buildOrderBodyModal(String sessionId) {
        var bodyInput = TextInput.create(ORDER_BODY_INPUT_ID, "Order body", TextInputStyle.PARAGRAPH)
                .setRequired(true)
                .setMinLength(1)
                .setMaxLength(2000)
                .setPlaceholder("Type the full order details here...")
                .build();

        return Modal.create(BODY_MODAL_ID_PREFIX + sessionId, "Create Primo Order")
                .addActionRow(bodyInput)
                .build();
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

    private static class PendingOrderSession {
        private final long userId;
        private final long guildId;
        private final Instant expiresAt;
        private String forumId;
        private List<String> selectedTagIds;

        private PendingOrderSession(long userId, long guildId, Instant expiresAt, String forumId, List<String> selectedTagIds) {
            this.userId = userId;
            this.guildId = guildId;
            this.expiresAt = expiresAt;
            this.forumId = forumId;
            this.selectedTagIds = selectedTagIds;
        }
    }
}
