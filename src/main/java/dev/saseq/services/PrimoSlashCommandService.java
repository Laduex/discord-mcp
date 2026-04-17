package dev.saseq.services;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import net.dv8tion.jda.api.interactions.commands.OptionType;
import net.dv8tion.jda.api.interactions.commands.build.CommandData;
import net.dv8tion.jda.api.interactions.commands.build.Commands;
import net.dv8tion.jda.api.interactions.commands.build.OptionData;
import net.dv8tion.jda.api.interactions.commands.build.SubcommandData;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.text.DecimalFormat;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

@Service
public class PrimoSlashCommandService extends ListenerAdapter {

    private static final String COMMAND_NAME = "primo";
    private static final String SUBCOMMAND_VAT = "vat";
    private static final String SUBCOMMAND_UTAK = "utak";
    private static final String OPTION_UIDS = "uids";
    private static final String OPTION_TIMEZONE = "timezone";
    private static final BigDecimal ONE_HUNDRED = BigDecimal.valueOf(100);
    private static final BigDecimal DEFAULT_VAT_RATE = BigDecimal.valueOf(12);
    private static final MathContext MC = MathContext.DECIMAL64;
    private static final DateTimeFormatter UTAK_DATE_TIME_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final String DEFAULT_UTAK_GRAPHQL_URL = "https://fingql.utak.io/graphql";
    private static final String DEFAULT_UTAK_TIMEZONE = "Asia/Manila";
    private static final String UTAK_STATS_QUERY = """
            query GetTransactionItemStats($uids: [String], $startDate: String, $endDate: String) {
              getTransactionItemStats(uids: $uids, startDate: $startDate, endDate: $endDate) {
                totalNetSales
                noOfTransactions
                totalRefunds
                profit
              }
            }
            """;

    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    @Value("${UTAK_GRAPHQL_URL:" + DEFAULT_UTAK_GRAPHQL_URL + "}")
    private String utakGraphqlUrl;

    @Value("${UTAK_UIDS:}")
    private String defaultUtakUids;

    @Value("${UTAK_TIMEZONE:" + DEFAULT_UTAK_TIMEZONE + "}")
    private String defaultUtakTimezone;

    @Value("${UTAK_GRAPHQL_AUTH_HEADER:}")
    private String utakGraphqlAuthHeader;

    @Value("${UTAK_GRAPHQL_COOKIE:}")
    private String utakGraphqlCookie;

    public PrimoSlashCommandService(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newHttpClient();
    }

    public static CommandData buildPrimoSlashCommand() {
        var vatSubcommand = new SubcommandData(SUBCOMMAND_VAT, "Calculate VAT totals for POS or invoices")
                .addOptions(
                        new OptionData(OptionType.NUMBER, "amount", "Amount to calculate from", true),
                        new OptionData(OptionType.STRING, "basis", "Is amount gross (VAT inclusive) or net (VAT exclusive)?", true)
                                .addChoice("gross", "gross")
                                .addChoice("net", "net"),
                        new OptionData(OptionType.NUMBER, "vat_rate", "VAT rate in percent (default: 12)", false)
                );

        var utakSubcommand = new SubcommandData(SUBCOMMAND_UTAK, "Show Utak Total Net Sales (as of now)")
                .addOptions(
                        new OptionData(OptionType.STRING, OPTION_UIDS, "Comma-separated Utak branch UIDs (optional override)", false),
                        new OptionData(OptionType.STRING, OPTION_TIMEZONE, "Timezone, e.g. Asia/Manila (optional)", false)
                );

        var primoCommand = Commands.slash(COMMAND_NAME, "Primo utility commands")
                .addSubcommands(vatSubcommand, utakSubcommand);
        return primoCommand;
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
        if (SUBCOMMAND_UTAK.equals(subcommand)) {
            handleUtak(event);
            return;
        }

        event.reply("Unknown subcommand. Use `/primo vat` or `/primo utak`.").setEphemeral(true).queue();
    }

    private void handleVat(SlashCommandInteractionEvent event) {
        var amountOption = event.getOption("amount");
        var basisOption = event.getOption("basis");
        var vatRateOption = event.getOption("vat_rate");

        if (amountOption == null || basisOption == null) {
            event.reply("Missing required options. Use `/primo vat amount:<number> basis:<gross|net>`.").setEphemeral(true).queue();
            return;
        }

        BigDecimal amount = BigDecimal.valueOf(amountOption.getAsDouble());
        String basis = basisOption.getAsString();
        BigDecimal vatRate = vatRateOption != null
                ? BigDecimal.valueOf(vatRateOption.getAsDouble())
                : DEFAULT_VAT_RATE;

        if (amount.compareTo(BigDecimal.ZERO) < 0) {
            event.reply("Amount must be zero or greater.").setEphemeral(true).queue();
            return;
        }
        if (vatRate.compareTo(BigDecimal.ZERO) < 0) {
            event.reply("VAT rate must be zero or greater.").setEphemeral(true).queue();
            return;
        }

        VatResult result = calculateVat(amount, vatRate, basis);

        String response = """
                **Primo VAT Calculator**
                Basis: %s
                Rate: %s%%
                Net (VAT Exclusive): %s
                VAT: %s
                Gross (VAT Inclusive): %s
                """.formatted(
                result.basisLabel,
                formatNumber(vatRate),
                formatMoney(result.netAmount),
                formatMoney(result.vatAmount),
                formatMoney(result.grossAmount)
        );

        event.reply(response).queue();
    }

    private void handleUtak(SlashCommandInteractionEvent event) {
        String uidsRaw = event.getOption(OPTION_UIDS) != null
                ? event.getOption(OPTION_UIDS).getAsString()
                : defaultUtakUids;
        List<String> uids = parseCommaSeparated(uidsRaw);
        if (uids.isEmpty()) {
            event.reply("No Utak branch UIDs configured. Set `UTAK_UIDS` or pass `uids:` in `/primo utak`.").setEphemeral(true).queue();
            return;
        }

        String timezone = event.getOption(OPTION_TIMEZONE) != null
                ? event.getOption(OPTION_TIMEZONE).getAsString()
                : defaultUtakTimezone;
        ZoneId zoneId;
        try {
            zoneId = ZoneId.of(timezone);
        } catch (Exception ex) {
            event.reply("Invalid timezone. Example: `Asia/Manila`.").setEphemeral(true).queue();
            return;
        }

        ZonedDateTime now = ZonedDateTime.now(zoneId);
        ZonedDateTime start = now.toLocalDate().atStartOfDay(zoneId);
        String startDate = start.format(UTAK_DATE_TIME_FORMAT);
        String endDate = now.format(UTAK_DATE_TIME_FORMAT);

        try {
            JsonNode stats = fetchUtakStats(uids, startDate, endDate);
            if (stats == null || stats.isNull()) {
                event.reply("UTAK returned no data for the requested range.").setEphemeral(true).queue();
                return;
            }

            BigDecimal totalNetSales = BigDecimal.valueOf(stats.path("totalNetSales").asDouble(0D));
            BigDecimal totalRefunds = BigDecimal.valueOf(stats.path("totalRefunds").asDouble(0D));
            BigDecimal profit = BigDecimal.valueOf(stats.path("profit").asDouble(0D));
            int noOfTransactions = stats.path("noOfTransactions").asInt(0);

            String response = """
                    **Primo Utak Sales**
                    Total Net Sales: %s
                    Transactions: %d
                    Total Refunds: %s
                    Profit: %s
                    As of: %s (%s)
                    Range: %s to %s
                    Branch UIDs: %d
                    """.formatted(
                    formatMoney(roundMoney(totalNetSales)),
                    noOfTransactions,
                    formatMoney(roundMoney(totalRefunds)),
                    formatMoney(roundMoney(profit)),
                    endDate,
                    zoneId,
                    startDate,
                    endDate,
                    uids.size()
            );

            event.reply(response).queue();
        } catch (Exception ex) {
            event.reply("Failed to fetch Utak sales: " + safeErrorMessage(ex)).setEphemeral(true).queue();
        }
    }

    private JsonNode fetchUtakStats(List<String> uids, String startDate, String endDate) throws IOException, InterruptedException {
        Map<String, Object> variables = new HashMap<>();
        variables.put("uids", uids);
        variables.put("startDate", startDate);
        variables.put("endDate", endDate);

        Map<String, Object> payload = new HashMap<>();
        payload.put("query", UTAK_STATS_QUERY);
        payload.put("variables", variables);

        HttpRequest.Builder requestBuilder = HttpRequest.newBuilder()
                .uri(URI.create(utakGraphqlUrl))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(payload)));

        if (utakGraphqlAuthHeader != null && !utakGraphqlAuthHeader.isBlank()) {
            requestBuilder.header("Authorization", utakGraphqlAuthHeader.trim());
        }
        if (utakGraphqlCookie != null && !utakGraphqlCookie.isBlank()) {
            requestBuilder.header("Cookie", utakGraphqlCookie.trim());
        }

        HttpResponse<String> response = httpClient.send(requestBuilder.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("HTTP " + response.statusCode());
        }

        JsonNode body = objectMapper.readTree(response.body());
        JsonNode errors = body.path("errors");
        if (errors.isArray() && !errors.isEmpty()) {
            String message = errors.get(0).path("message").asText("Unknown GraphQL error");
            throw new IOException(message);
        }
        return body.path("data").path("getTransactionItemStats");
    }

    private List<String> parseCommaSeparated(String raw) {
        List<String> out = new ArrayList<>();
        if (raw == null || raw.isBlank()) {
            return out;
        }
        for (String entry : raw.split(",")) {
            String value = entry.trim();
            if (!value.isEmpty()) {
                out.add(value);
            }
        }
        return out;
    }

    private String safeErrorMessage(Exception ex) {
        String message = ex.getMessage();
        if (message == null || message.isBlank()) {
            return ex.getClass().getSimpleName();
        }
        return message;
    }

    private VatResult calculateVat(BigDecimal amount, BigDecimal vatRatePercent, String basis) {
        BigDecimal rateFraction = vatRatePercent.divide(ONE_HUNDRED, MC);
        BigDecimal net;
        BigDecimal vat;
        BigDecimal gross;
        String basisLabel;

        if ("gross".equalsIgnoreCase(basis)) {
            // POS style: VAT from gross (inclusive): VAT = gross * rate / (100 + rate)
            gross = amount;
            BigDecimal divisor = BigDecimal.ONE.add(rateFraction, MC);
            net = gross.divide(divisor, MC);
            vat = gross.subtract(net, MC);
            basisLabel = "Gross (VAT Inclusive)";
        } else if ("net".equalsIgnoreCase(basis)) {
            net = amount;
            vat = net.multiply(rateFraction, MC);
            gross = net.add(vat, MC);
            basisLabel = "Net (VAT Exclusive)";
        } else {
            throw new IllegalArgumentException("basis must be either 'gross' or 'net'");
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
