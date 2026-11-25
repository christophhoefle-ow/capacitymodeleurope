// Power Query query D_Coordinates - loads substation_coordinates.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "substation_coordinates.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
    Typed = Table.TransformColumnTypes(Empty, {{"latitude", type number}, {"longitude", type number}}, "en-US")
in
    Typed
