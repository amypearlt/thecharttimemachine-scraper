import argparse
import logging
from pathlib import Path
import pandas as pd

KEY = ["week", "position", "artist", "song"]
MAX_GENRES = 6
MAX_STYLES = 8
MIN_DATE = pd.Timestamp(1952,11,14)
MAX_DATE = pd.Timestamp(1999,12,26)

def parse_week(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series.str.strip(), format="%m/%d/%y", errors="coerce")
    dates = dates.where(dates.dt.year < 2000, dates - pd.DateOffset(years=100)) #YY maps 00-68 to 2000-2068
    return dates

def flag_songs(df: pd.DataFrame) -> pd.DataFrame:
    genre_no = df["genre"].str.count(r"\|") + 1 #Some songs have an excess of genres/styles, possibly due to matching to multiple releases
    style_no = df["style"].str.count(r"\|") + 1
    df.loc[genre_no > MAX_GENRES, "genre"] = "INVALID" #Marked for overriding
    df.loc[style_no > MAX_STYLES, "style"] = "INVALID"

    df.loc[df["genre"].isna(), "genre"] = "INVALID" #1 song does not list a genre on its webpage
    df.loc[df["genre"] == "INVALID", "style"] = "INVALID" #If genre is invalid, style is invalid too
    df.loc[df["style"] == "INVALID", "genre"] = "INVALID" #vice versa
    return df

def apply_override(df: pd.DataFrame, override: pd.DataFrame) -> pd.DataFrame:
    #Overrides incorrect genre/style columns, sourced from a manual reference of Discogs's database (1st release of master release), which TCTM pulls their genre data from. Data imputation
    df = df.merge(override, on="song_url", how="left", suffixes=("", "_override"), validate="many_to_one")
    for column in ["genre", "style"]:
        df[column] = df[f"{column}_override"].combine_first(df[column])
        df = df.drop(columns=[f"{column}_override"])
    df["style"] = df["style"].replace("INVALID", pd.NA)
    return df

def drop(df: pd.DataFrame) -> pd.DataFrame:
    dupes = df.duplicated()
    if dupes.any(): 
        logging.warning(f"Found duplicate rows:\n{df.loc[dupes].to_string(index=False)}\n")
        df = df.drop_duplicates()

    key_dupes = df.duplicated(subset=KEY)
    if key_dupes.any():
        logging.warning(f"Found key duplicate rows (week, position, artist, song):\n{df.loc[key_dupes].to_string(index=False)}\n")
        df = df.drop_duplicates(subset=KEY)

    missing_key = df[KEY].isna().any(axis=1)
    if missing_key.any():
        logging.warning(f"Found rows missing key columns (week, position, artist, song):\n{df.loc[missing_key].to_string(index=False)}\n")
        df = df.dropna(subset=KEY)
    return df

def validate(df: pd.DataFrame, categories: dict) -> pd.DataFrame:
    invalid_weeks = ~df["week"].between(MIN_DATE, MAX_DATE)
    if invalid_weeks.any():
        logging.warning(f"Found weeks outside range of {MIN_DATE:%Y-%m-%d} to {MAX_DATE:%Y-%m-%d}:\n{df.loc[invalid_weeks].to_string(index=False)}\n")

    invalid_positions = ~df["position"].between(1,100)
    if invalid_positions.any():
        logging.warning(f"Found positions outside range of 1 to 100:\n{df.loc[invalid_positions].to_string(index=False)}\n")

    for column in ["genre", "style"]:
        tagged = df.dropna(subset=[column])
        repeated_tags = tagged[column].str.split("|").map(lambda t: len(t) != len(set(t)))
        if repeated_tags.any():
            logging.warning(f"Found rows with repeated {column}s:\n{tagged.loc[repeated_tags].to_string(index=False)}")
        
        tags = explode_tags(tagged, column)[column]
        invalid_tags = set(tags) - categories[column]
        if invalid_tags:
            invalid_tags = tagged[column].str.split("|").map(lambda t: any(tag not in categories[column] for tag in t))
            logging.warning(f"Found rows with invalid {column}s:\n{tagged.loc[invalid_tags].to_string(index=False)}")

    missing_values = df[["label", "genre"]].isna().any(axis=1)
    if missing_values.any():
        logging.warning(f"Found rows missing required columns (label, genre):\n{df.loc[missing_values].to_string(index=False)}\n")
    return df

def explode_tags(df: pd.DataFrame, column: str) -> pd.DataFrame: #convert to categorical??
    tags = df.assign(**{column: df[column].str.split("|")}).explode(column)
    return tags

def clean(df: pd.DataFrame, override: pd.DataFrame, categories: dict) -> pd.DataFrame:
    df = df.copy()

    text_columns = df.select_dtypes(include=["object", "string"]).columns
    for column in text_columns: #Removing leading, trailing and inner whitespace
        df[column] = df[column].str.strip().str.replace(r"\s+", " ", regex=True)
    df["song"] = df["song"].str.replace(r"\s*\(Reentry\)\s*$", "", regex=True) #Remove reentry tags (added by TCTM), reducing redundancy
    df[text_columns] = df[text_columns].replace("", pd.NA) #Mark empty values

    df["position"] = pd.to_numeric(df["position"], errors="coerce").astype("Int64") #Type casting
    df["week"] = parse_week(df["week"])

    df = flag_songs(df)
    df = apply_override(df, override) #Note: List of genres/styles are kept in alphabetic order

    df = df.drop(columns=["url", "song_url"], errors="ignore") #URLs are irrelevant to the data
    df = df[["week", "position", "artist", "song", "label", "genre", "style"]] #Reorder columns

    df = drop(df)
    df = validate(df, categories)

    df = df.sort_values(["week", "position", "artist", "song"]).reset_index(drop=True)
    return df

def report(raw: pd.DataFrame, df: pd.DataFrame) -> None:
    missing_styles = df["style"].isna().sum()
    logging.info(f"Found {missing_styles} rows with no styles")

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("numexpr.utils").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", default="output/charts.csv")
    parser.add_argument("-o", "--output", default="output/charts_clean.csv")
    args = parser.parse_args()
 
    categories = {
        "genre": set(Path("genre.txt").read_text(encoding="utf-8").splitlines()),
        "style": set(Path("style.txt").read_text(encoding="utf-8").splitlines())
    }
    override = pd.read_csv("OverrideChartsClean.csv")
    raw = pd.read_csv(args.input, dtype=str)
    df = clean(raw, override, categories)
    report(raw, df)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)

if __name__ == "__main__":
    main()