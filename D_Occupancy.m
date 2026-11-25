// Power Query query D_Occupancy - loads occupancy_mastr.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "occupancy_mastr.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
    Typed = Table.TransformColumnTypes(Empty, {{"occupied_feed_in_mw", type number}, {"occupied_load_mw", type number}, {"requested_feed_in_mw", type number}, {"requested_load_mw", type number}}, "en-US")
in
    Typed
