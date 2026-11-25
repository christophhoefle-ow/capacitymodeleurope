// Power Query query D_Substations - loads master_substations.csv
let
    Source = Csv.Document(Web.Contents(GitHubBaseUrl, [RelativePath = "master_substations.csv"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Empty = Table.ReplaceValue(Header, "", null, Replacer.ReplaceValue, Table.ColumnNames(Header)),
in
    Empty
