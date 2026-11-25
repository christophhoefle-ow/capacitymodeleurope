// Power Query query D_ExpSections - loads grid_expansion_sections.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "grid_expansion_sections.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
    Typed = Table.TransformColumnTypes(Empty, {{"length_km", type number}, {"built_km", type number}}, "en-US")
in
    Typed
