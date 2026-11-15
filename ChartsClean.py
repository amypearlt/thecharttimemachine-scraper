import argparse
from pathlib import Path
import pandas as pd

MAX_GENRES = 6
MAX_STYLES = 8

KEY = ["week", "position", "song", "artist"]

def parse_week(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series.str.strip(), format="%m/%d/%y", errors="coerce")
    dates = dates.where(dates.dt.year < 2000, dates - pd.DateOffset(years=100)) #YY maps 00-68 to 2000-2068
    return dates

def flag_songs(df: pd.DataFrame) -> pd.DataFrame:
    genre_no = df["genre"].str.count(r"\|") + 1 #Some songs have an excess of genres/styles, possibly due to matching to multiple releases
    style_no = df["style"].str.count(r"\|") + 1
    df.loc[genre_no > MAX_GENRES, "genre"] = "INVALID"
    df.loc[style_no > MAX_STYLES, "style"] = "INVALID" #then override invalid values

    df.loc[df["genre"].isna(), "genre"] = "INVALID" #1 song does not list a genre on its webpage
    df.loc[df["genre"] == "INVALID", "style"] = "INVALID" #If genre is invalid, style is invalid too
    df.loc[df["style"] == "INVALID", "genre"] = "INVALID" #vice versa
    #decreased style threshold?
    return df

def apply_override(df: pd.DataFrame, override: pd.DataFrame) -> pd.DataFrame:
    df = df.merge(override, on="song_url", how="left", suffixes=("", "_override"), validate="many_to_one")
    for column in ["genre", "style"]:
        df[column] = df[f"{column}_override"].combine_first(df[column])
        df = df.drop(columns=[f"{column}_override"])
    df["style"] = df["style"].replace("INVALID", pd.NA)
    return df

def validate(df: pd.DataFrame) -> pd.DataFrame:
    #Overrides incorrect genre columns, sourced from a manual reference of Discogs's database (1st release of master release), which TCTM pulls their genre data from. Data imputation
    return df

def clean(df: pd.DataFrame, override: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    text_columns = df.select_dtypes(include=["object"]).columns
    for column in text_columns: #Removing leading, trailing and inner whitespace
        df[column] = df[column].str.strip().str.replace(r"\s+", " ", regex=True)
    df[text_columns] = df[text_columns].replace("", pd.NA) #Mark empty values

    df["position"] = pd.to_numeric(df["position"], errors="coerce").astype("Int64") #Type casting
    df["week"] = parse_week(df["week"])

    #list of genres and styles are kept in alphabetic order

    df = flag_songs(df)

    df = apply_override(df, override)

    #log and drop dupes?& key dupes

    df = df.drop(columns=["url", "song_url"], errors="ignore") #URLs are irrelevant to the data
    df = df[["week", "position", "artist", "song", "label", "genre", "style"]] #Reorder columns
    #separate reissues/renetry tags etc from song??

    df = validate(df)

    df = df.sort_values(["week", "position", "artist", "song"]).reset_index(drop=True)
    return df

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", default="output/charts.csv")
    parser.add_argument("-o", "--output", default="output/charts_clean.csv")
    args = parser.parse_args()

    override = pd.read_csv("OverrideChartsClean.csv")
    raw = pd.read_csv(args.input, dtype=str)
    df = clean(raw, override)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)

if __name__ == "__main__":
    main()