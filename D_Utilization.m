// Power Query query D_Utilization - loads utilization_monthly.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "utilization_monthly.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
    Typed = Table.TransformColumnTypes(Empty, {{"month", type date}, {"fmax_mw", type number}, {"hours", Int64.Type}, {"util_sum", type number}, {"util_max", type number}, {"hours_high", Int64.Type}, {"hours_overload", Int64.Type}, {"hours_binding", Int64.Type}}, "en-US")
in
    Typed
