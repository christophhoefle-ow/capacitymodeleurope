// Power Query query D_Lines - loads master_lines.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "master_lines.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
    Typed = Table.TransformColumnTypes(Empty, {{"voltage_kv", type number}, {"imax_period_1_a", type number}, {"imax_period_2_a", type number}, {"imax_period_3_a", type number}, {"imax_period_4_a", type number}, {"imax_period_5_a", type number}, {"imax_period_6_a", type number}, {"imax_fixed_a", type number}, {"dlr_min_a", type number}, {"dlr_max_a", type number}, {"r_ohm", type number}, {"x_ohm", type number}, {"b_us", type number}, {"length_km", type number}}, "en-US")
in
    Typed
