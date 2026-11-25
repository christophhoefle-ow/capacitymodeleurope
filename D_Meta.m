// Power Query query D_Meta - loads meta.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "meta.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
in
    Empty
