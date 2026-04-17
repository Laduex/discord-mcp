package dev.saseq.services;

import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import net.dv8tion.jda.api.interactions.commands.OptionType;
import net.dv8tion.jda.api.interactions.commands.build.CommandData;
import net.dv8tion.jda.api.interactions.commands.build.Commands;
import net.dv8tion.jda.api.interactions.commands.build.OptionData;
import net.dv8tion.jda.api.interactions.commands.build.SubcommandData;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.text.DecimalFormat;

@Service
public class PrimoSlashCommandService extends ListenerAdapter {

    private static final String COMMAND_NAME = "primo";
    private static final String SUBCOMMAND_VAT = "vat";
    private static final BigDecimal ONE_HUNDRED = BigDecimal.valueOf(100);
    private static final BigDecimal FIXED_VAT_RATE = BigDecimal.valueOf(12);
    private static final MathContext MC = MathContext.DECIMAL64;

    public static CommandData buildPrimoSlashCommand() {
        var vatSubcommand = new SubcommandData(SUBCOMMAND_VAT, "Calculate VAT totals for POS or invoices")
                .addOptions(
                        new OptionData(OptionType.NUMBER, "amount", "Amount to calculate from", true),
                        new OptionData(OptionType.STRING, "basis", "Select whether the amount is VAT Inclusive or VAT Exclusive", true)
                                .addChoice("VAT Inclusive", "inclusive")
                                .addChoice("VAT Exclusive", "exclusive")
                );

        return Commands.slash(COMMAND_NAME, "Primo utility commands")
                .addSubcommands(vatSubcommand);
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

        event.reply("Unknown subcommand. Use `/primo vat`.").setEphemeral(true).queue();
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
