// Power Query query D_Transformers - loads master_transformers.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "master_transformers.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
    Typed = Table.TransformColumnTypes(Empty, {{"imax_min_a", type number}, {"imax_max_a", type number}, {"imax_fixed_a", type number}, {"u_primary_kv", type number}, {"u_secondary_kv", type number}, {"r_ohm", type number}, {"x_ohm", type number}, {"b_us", type number}, {"g_us", type number}, {"angle_deg", type number}, {"du_phase_pct", type number}, {"du_angle_pct", type number}}, "en-US")
in
    Typed
