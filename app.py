import os
from typing import List, Optional

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi import Response, Depends

import pandas as pd
import numpy as np
import re
from typing import Dict, Tuple
import matplotlib.pyplot as plt


# Application setup (FastAPI with static and templates)
app = FastAPI(title="Faculty Quarters Electricity Management System")


# Data directories and files
DATA_DIR = "data"
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
PLOTS_DIR = "."
MASTER_DATA_PATH = os.path.join(DATA_DIR, "master_data.csv")
ACTIONS_LOG_PATH = os.path.join(DATA_DIR, "actions.log")


# Ensure required directories exist on startup
def ensure_directories(directories: List[str]) -> None:
    for d in directories:
        os.makedirs(d, exist_ok=True)

def load_master_data(path: str) -> Optional[pd.DataFrame]:
    if not os.path.isfile(path):
        return None
    try:
        df = pd.read_csv(path)
        return df
    except Exception:
        return None

def save_master_data(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False)

def read_input_file(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    df: Optional[pd.DataFrame] = None
    if ext in [".xls", ".xlsx"]:
        try:
            df = pd.read_excel(path)
        except Exception:
            df = pd.read_excel(path, header=None)
    elif ext in [".csv", ".txt"]:
        try:
            df = pd.read_csv(path)
        except Exception:
            df = pd.read_csv(path, header=None)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    if df is None:
        raise ValueError("Failed to read file")
    try:
        if _looks_like_gulmohar(path, df):
            parsed = _parse_gulmohar_format(path)
            if isinstance(parsed, pd.DataFrame) and len(parsed.columns) >= 3:
                df = parsed
    except Exception:
        pass
    return df

def _normalize(s: str) -> str:
    s = str(s or "")
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()

def _parse_gulmohar_format(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    raw = pd.read_excel(path, header=None) if ext in [".xls", ".xlsx"] else pd.read_csv(path, header=None)
    header_idx = None
    for i in range(min(30, len(raw))):
        row = [str(x) for x in list(raw.iloc[i].values)]
        vals = [_normalize(x) for x in row]
        if any(v.startswith("sl.no") for v in vals) or any("name of the employee" in v for v in vals):
            header_idx = i
            break
    if header_idx is None:
        return raw
    header = [_normalize(x) for x in list(raw.iloc[header_idx].values)]
    data = raw.iloc[header_idx + 1 :].reset_index(drop=True)
    data.columns = header
    data = data.dropna(how="all")
    mapping = {
        "sl.no": "Serial_No",
        "name of the employee": "Name",
        "energy meter si.no.": "Meter_No",
        "quarters no. (house no.)": "House_No",
        "starting reading": "Prev_Reading",
        "final reading": "Current_Reading",
        "consumption in kwh": "Units_Consumed",
        "unit rate (rs.)": "Unit_Rate",
        "amount per month in rs.": "Cost",
        "rounded-off in rs.": "Rounded_Amount",
        "remarks": "Remarks",
    }
    cols2 = []
    for c in data.columns:
        cols2.append(mapping.get(c, re.sub(r"[^A-Za-z0-9_]+", "_", c.strip().title()).strip("_")))
    data.columns = cols2
    if "Serial_No" in data.columns:
        def _num(x):
            try:
                return int(str(x).strip())
            except Exception:
                return None
        data["Serial_No"] = data["Serial_No"].apply(_num)
        data = data.dropna(subset=["Serial_No"]).reset_index(drop=True)
    for col in ["Prev_Reading", "Current_Reading", "Units_Consumed", "Unit_Rate", "Cost", "Rounded_Amount"]:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    top_text = [" ".join([str(x) for x in list(raw.iloc[i].values)]) for i in range(0, header_idx)]
    dates = []
    for t in top_text:
        dates += re.findall(r"\b\d{2}\.\d{2}\.\d{4}\b", t)
    period_start = dates[0] if len(dates) > 0 else None
    period_end = dates[1] if len(dates) > 1 else None
    if period_start:
        try:
            data["Period_Start"] = pd.to_datetime(period_start, format="%d.%m.%Y", errors="coerce")
        except Exception:
            data["Period_Start"] = period_start
    if period_end:
        try:
            data["Period_End"] = pd.to_datetime(period_end, format="%d.%m.%Y", errors="coerce")
        except Exception:
            data["Period_End"] = period_end
    if "Period_End" in data.columns:
        data["Date"] = data["Period_End"]
    else:
        data["Date"] = pd.NaT
    phase = None
    for i in range(0, header_idx):
        vals = [_normalize(x) for x in list(raw.iloc[i].values)]
        joined = " ".join(vals)
        m = re.search(r"phase[-\s]*([a-z0-9]+)", joined)
        if m:
            phase = m.group(1).upper()
            break
    if phase:
        data["Phase"] = phase
    return data

def _looks_like_gulmohar(path: str, df: pd.DataFrame) -> bool:
    cols = [str(c).lower() for c in df.columns]
    if any(c.startswith("unnamed") for c in cols) or 0 in df.columns:
        return True
    try:
        ext = os.path.splitext(path)[1].lower()
        raw = pd.read_excel(path, header=None) if ext in [".xls", ".xlsx"] else pd.read_csv(path, header=None)
        for i in range(min(40, len(raw))):
            row = " ".join([str(x) for x in list(raw.iloc[i].values)]).lower()
            if ("gulmohar enclave" in row) or ("name of the employee" in row) or ("consumption in kwh" in row):
                return True
    except Exception:
        pass
    return False

def guess_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    cols_lower = {c.lower(): c for c in df.columns}
    def find_one(candidates: List[str]) -> Optional[str]:
        for cand in candidates:
            for key, orig in cols_lower.items():
                if cand in key:
                    return orig
        return None
    date_col = find_one(["date", "month", "reading_date", "meter_date"])
    units_col = find_one(["unit", "consum", "kwh"])
    reading_col = find_one(["reading", "meter_reading", "current_reading", "prev_reading"])
    cost_col = find_one(["cost", "bill", "amount", "price"])
    if units_col is None and reading_col is not None:
        units_col = reading_col
    return {"date": date_col, "units": units_col, "reading": reading_col, "cost": cost_col}

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    colmap = guess_columns(df)
    if colmap["date"]:
        try:
            df[colmap["date"]] = pd.to_datetime(df[colmap["date"]], errors="coerce")
        except Exception:
            pass
    for key in ["units", "cost"]:
        col = colmap.get(key)
        if col and col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(how="all")
    df = df.fillna(method="ffill").fillna(method="bfill")
    subset_cols = [c for c in [colmap.get("date"), colmap.get("units")] if c]
    if subset_cols:
        df = df.drop_duplicates(subset=subset_cols)
    else:
        df = df.drop_duplicates()
    return df

def integrate_data(master_df: Optional[pd.DataFrame], new_df: pd.DataFrame) -> pd.DataFrame:
    if master_df is None or master_df.empty:
        combined = new_df.copy()
    else:
        combined = pd.concat([master_df, new_df], ignore_index=True)
    combined = clean_data(combined)
    return combined

def discretize_and_bin(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    colmap = guess_columns(df)
    units_col = colmap.get("units")
    if units_col and units_col in df.columns:
        series = df[units_col].dropna()
        try:
            df["usage_bin"] = pd.qcut(df[units_col], q=3, labels=["Low", "Medium", "High"])
        except Exception:
            try:
                bins = [-np.inf, series.quantile(0.33), series.quantile(0.66), np.inf]
                df["usage_bin"] = pd.cut(df[units_col], bins=bins, labels=["Low", "Medium", "High"])
            except Exception:
                df["usage_bin"] = pd.cut(df[units_col], bins=3, labels=["Low", "Medium", "High"])
    return df

def encode_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "usage_bin" in df.columns:
        mapping = {"Low": 0, "Medium": 1, "High": 2}
        df["usage_bin_encoded"] = df["usage_bin"].map(mapping)
    return df

def transform_and_smooth(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    colmap = guess_columns(df)
    units_col = colmap.get("units")
    date_col = colmap.get("date")
    if units_col and units_col in df.columns:
        df["units_log"] = np.log1p(df[units_col].clip(lower=0))
    if date_col and date_col in df.columns and pd.api.types.is_datetime64_any_dtype(df[date_col]):
        df_sorted = df.sort_values(by=date_col).set_index(date_col)
        df_monthly = df_sorted.resample("M").sum(numeric_only=True)
        df_monthly["units_rolling_mean_3m"] = df_monthly.get(units_col, pd.Series(dtype=float)).rolling(window=3, min_periods=1).mean()
        df_monthly = df_monthly.reset_index()
    return df

def validate_data(df: pd.DataFrame) -> Dict[str, int]:
    report = {"total_rows": int(len(df)), "invalid_units": 0, "duplicates_removed": 0}
    colmap = guess_columns(df)
    units_col = colmap.get("units")
    if units_col and units_col in df.columns:
        invalid = df[df[units_col] < 0]
        report["invalid_units"] = int(len(invalid))
    report["duplicates_removed"] = int(df.duplicated().sum())
    return report

def run_full_pipeline(new_df: pd.DataFrame, master_df: Optional[pd.DataFrame]) -> Tuple[pd.DataFrame, Dict[str, object]]:
    collected = clean_data(new_df)
    integrated = integrate_data(master_df, collected)
    binned = discretize_and_bin(integrated)
    encoded = encode_categoricals(binned)
    transformed = transform_and_smooth(encoded)
    validation_report = validate_data(transformed)
    pipeline_report: Dict[str, object] = {
        "rows_after_integration": int(len(integrated)),
        "rows_final": int(len(transformed)),
        "validation": validation_report,
    }
    return transformed, pipeline_report

def get_eda_summary(df: pd.DataFrame) -> Dict[str, object]:
    summary: Dict[str, object] = {}
    summary["shape"] = list(df.shape)
    summary["columns"] = list(df.columns)
    summary["dtypes"] = {c: str(t) for c, t in df.dtypes.items()}
    try:
        desc = df.describe(include="all").fillna(0)
        summary["describe"] = desc.to_dict()
    except Exception:
        summary["describe"] = {}
    summary["head"] = df.head(10).to_dict(orient="records")
    return summary

def _latest_upload_file() -> Optional[str]:
    try:
        files = []
        if os.path.isdir(UPLOADS_DIR):
            for name in os.listdir(UPLOADS_DIR):
                path = os.path.join(UPLOADS_DIR, name)
                if os.path.isfile(path) and name.lower().endswith((".csv", ".xls", ".xlsx")):
                    files.append((path, os.path.getmtime(path)))
        files.sort(key=lambda x: x[1], reverse=True)
        return files[0][0] if files else None
    except Exception:
        return None

def _guess_faculty_col(df: pd.DataFrame) -> Optional[str]:
    candidates = ["name", "employee", "house", "quarters", "flat"]
    for c in df.columns:
        key = str(c).lower()
        if any(k in key for k in candidates):
            return c
    return None

@app.get("/api/eda_raw")
async def api_eda_raw():
    path = _latest_upload_file()
    if not path:
        return {"status": "empty", "message": "No uploads found"}
    try:
        df = read_input_file(path)
        return {"status": "success", "summary": get_eda_summary(df), "file": os.path.basename(path)}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": f"Failed to read latest upload: {exc}"})

@app.get("/api/eda_engineered")
async def api_eda_engineered():
    df = load_master_data(MASTER_DATA_PATH)
    if df is None or df.empty:
        return {"status": "empty", "message": "No master data"}
    colmap = guess_columns(df)
    units_col = colmap.get("units")
    reading_col = colmap.get("reading")
    cost_col = colmap.get("cost")
    date_col = colmap.get("date")
    fac_col = _guess_faculty_col(df)

    features: Dict[str, object] = {}
    # usage bins
    for c in ["usage_bin", "usage_bin_encoded", "units_log"]:
        if c in df.columns:
            try:
                vc = df[c].value_counts(dropna=False).to_dict()
                features[f"{c}_counts"] = vc
            except Exception:
                pass

    # stats on units
    if units_col and units_col in df.columns:
        ser = pd.to_numeric(df[units_col], errors="coerce")
        features["usage_stats"] = {
            "mean": float(ser.mean()) if ser.notna().any() else None,
            "median": float(ser.median()) if ser.notna().any() else None,
            "std": float(ser.std()) if ser.notna().any() else None,
        }
        # outliers via z-score > 3
        try:
            s = ser.dropna()
            z = (s - s.mean()) / (s.std() if s.std() else 1)
            out_idx = list(z[abs(z) > 3].index)
            out_sample = df.loc[out_idx].head(10).to_dict(orient="records")
            features["outliers"] = {"count": int(len(out_idx)), "sample": out_sample}
        except Exception:
            features["outliers"] = {"count": 0}

    # monthly trend
    if date_col and date_col in df.columns:
        try:
            dt = pd.to_datetime(df[date_col], errors="coerce")
            tmp = pd.DataFrame({"date": dt, "units": pd.to_numeric(df.get(units_col, pd.Series()), errors="coerce")})
            tmp = tmp.dropna(subset=["date"]) 
            tmp["month"] = tmp["date"].dt.to_period("M").dt.to_timestamp()
            monthly = tmp.groupby("month")["units"].sum().reset_index()
            features["monthly_trend"] = [{"month": str(r["month"]).split(" ")[0], "units": float(r["units"])} for _, r in monthly.iterrows()]
            # seasonal by month-of-year
            tmp["moy"] = tmp["date"].dt.month
            seasonal = tmp.groupby("moy")["units"].sum().reset_index()
            features["seasonal_trend"] = [{"month": int(r["moy"]), "units": float(r["units"])} for _, r in seasonal.iterrows()]
        except Exception:
            pass

    # faculty-wise comparison
    if fac_col:
        try:
            grp = df.groupby(fac_col)
            comp = grp.agg({units_col: "mean", cost_col: "mean"}).reset_index()
            features["faculty_comparison"] = [
                {"faculty": str(r[fac_col]), "units_mean": float(r.get(units_col, 0) or 0), "cost_mean": float(r.get(cost_col, 0) or 0)}
                for _, r in comp.iterrows()
            ]
        except Exception:
            pass

    # correlation reading vs cost
    if reading_col and cost_col and reading_col in df.columns and cost_col in df.columns:
        try:
            numeric = df[[reading_col, cost_col]].apply(pd.to_numeric, errors="coerce").dropna()
            corr = float(numeric[reading_col].corr(numeric[cost_col])) if len(numeric) >= 2 else None
            features["correlation_reading_cost"] = corr
        except Exception:
            features["correlation_reading_cost"] = None

    return {"status": "success", "features": features}

def generate_visualizations(df: pd.DataFrame, out_dir: str) -> List[str]:
    ensure_directories([out_dir])
    plots: List[str] = []
    colmap = guess_columns(df)
    units_col = colmap.get("units")
    numeric = df.select_dtypes(include=[np.number]).copy()
    try:
        import seaborn as sns
        if numeric.shape[1] >= 2:
            corr = numeric.corr()
            plt.figure(figsize=(6, 4))
            sns.heatmap(corr, cmap="magma")
            fname = os.path.join(out_dir, "heatmap_corr.png")
            plt.tight_layout()
            plt.savefig(fname)
            plt.close()
            plots.append(f"/plots/{os.path.basename(fname)}")
    except Exception:
        if numeric.shape[1] >= 2:
            corr = numeric.corr()
            if not corr.isna().all().all():
                plt.figure(figsize=(6, 4))
                plt.imshow(corr.values, cmap="magma", interpolation="nearest")
                plt.colorbar()
                plt.xticks(range(len(corr.columns)), corr.columns, rotation=45)
                plt.yticks(range(len(corr.index)), corr.index)
                fname = os.path.join(out_dir, "heatmap_corr.png")
                plt.tight_layout()
                plt.savefig(fname)
                plt.close()
                plots.append(f"/plots/{os.path.basename(fname)}")
    if units_col and units_col in df.columns:
        plt.figure(figsize=(6, 4))
        df[units_col].dropna().hist(bins=20, color="#7c3aed")
        plt.title("Units Distribution")
        plt.xlabel("Units")
        plt.ylabel("Frequency")
        fname = os.path.join(out_dir, "units_hist.png")
        plt.tight_layout()
        plt.savefig(fname)
        plt.close()
        plots.append(f"/plots/{os.path.basename(fname)}")
    return plots

ensure_directories([DATA_DIR, UPLOADS_DIR, PLOTS_DIR])


def log_action(action: str, details: Optional[dict] = None) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ACTIONS_LOG_PATH, "a", encoding="utf-8") as f:
            import json, datetime
            entry = {"ts": datetime.datetime.utcnow().isoformat()+"Z", "action": action, "details": details or {}}
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def get_role(request: Request) -> str:
    return request.cookies.get("session_role", "")


def require_admin(request: Request):
    role = get_role(request)
    if role != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin required")
    return role


@app.get("/")
async def index(request: Request):
    """Render the main dashboard page."""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        return HTMLResponse(content=html)
    except Exception:
        return HTMLResponse(content="<h1>App</h1>")


 


@app.post("/upload")
async def upload_file(
    files: List[UploadFile] = File(...),
    mode: str = Form("stack"),
):
    """
    Handle file upload (Excel or CSV), read and merge into master dataset,
    run processing pipeline, and persist the updated master data.
    """
    saved_files: List[str] = []
    dataframes: List[pd.DataFrame] = []
    for file in files:
        original_filename = file.filename or "uploaded_file"
        save_path = os.path.join(UPLOADS_DIR, original_filename)
        with open(save_path, "wb") as fout:
            content = await file.read()
            fout.write(content)
        saved_files.append(original_filename)
        try:
            df_part = read_input_file(save_path)
            dataframes.append(df_part)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Failed to read file {original_filename}: {exc}"})

    if not dataframes:
        return JSONResponse(status_code=400, content={"status": "error", "message": "No files received"})

    try:
        new_df = pd.concat(dataframes, ignore_index=True)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": f"Failed to merge files: {exc}"})

    # Load existing master data if present
    master_df = None if mode.lower() == "overwrite" else load_master_data(MASTER_DATA_PATH)

    # Run pipeline: integrate new data & full processing
    processed_df, pipeline_report = run_full_pipeline(new_df, master_df)

    # Persist master data
    save_master_data(processed_df, MASTER_DATA_PATH)

    # Regenerate visualizations
    plot_files = generate_visualizations(processed_df, PLOTS_DIR)

    result = {
        "status": "success",
        "message": "Files uploaded and data processed",
        "rows_in_master": int(len(processed_df)),
        "pipeline_report": pipeline_report,
        "plots": plot_files,
        "saved_files": saved_files,
        "mode": mode,
    }
    log_action("upload", {"files": saved_files, "rows": int(len(processed_df)), "mode": mode})
    return result


@app.post("/api/process")
async def process_data():
    """
    Run processing on current master data and regenerate visualizations.
    """
    df = load_master_data(MASTER_DATA_PATH)
    if df is None or df.empty:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Master dataset is empty. Upload data first."})

    processed_df, pipeline_report = run_full_pipeline(df, None)
    save_master_data(processed_df, MASTER_DATA_PATH)
    plot_files = generate_visualizations(processed_df, PLOTS_DIR)

    result = {
        "status": "success",
        "message": "Data processed and visualizations regenerated",
        "rows_in_master": int(len(processed_df)),
        "pipeline_report": pipeline_report,
        "plots": plot_files,
    }
    log_action("process", {"rows": int(len(processed_df))})
    return result


@app.get("/api/eda")
async def eda_summary():
    """Return EDA summary for the current master dataset as JSON."""
    df = load_master_data(MASTER_DATA_PATH)
    if df is None or df.empty:
        return {"status": "empty", "message": "No master data found. Upload data to begin."}
    summary = get_eda_summary(df)
    return {"status": "success", "summary": summary}


@app.get("/api/master")
async def api_master():
    """Return master data records for interactive charts and filters (limited columns)."""
    df = load_master_data(MASTER_DATA_PATH)
    if df is None or df.empty:
        return {"status": "empty", "records": []}

    # Guess key columns
    colmap = guess_columns(df)
    cols = [c for c in [colmap.get("date"), colmap.get("units"), colmap.get("reading"), colmap.get("cost")] if c]
    data = df[cols].copy()
    # Normalize date to ISO string for JSON
    date_col = colmap.get("date")
    if date_col and date_col in data.columns:
        try:
            data[date_col] = pd.to_datetime(data[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    records = data.to_dict(orient="records")
    return {"status": "success", "records": records, "columns": cols}


@app.get("/api/master_full")
async def api_master_full():
    df = load_master_data(MASTER_DATA_PATH)
    if df is None or df.empty:
        return {"status": "empty", "records": [], "columns": []}
    data = df.copy()
    for c in list(data.columns):
        try:
            if pd.api.types.is_datetime64_any_dtype(data[c]):
                data[c] = pd.to_datetime(data[c], errors="coerce").dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    records = data.to_dict(orient="records")
    return {"status": "success", "records": records, "columns": list(data.columns)}


@app.get("/api/export/master.csv")
async def export_master_csv():
    df = load_master_data(MASTER_DATA_PATH)
    if df is None or df.empty:
        return JSONResponse(status_code=400, content={"status": "error", "message": "No master data"})
    import io
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=master_data.csv"})


@app.get("/plots/{name}")
async def get_plot(name: str):
    path = os.path.join(".", name)
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"status": "error"})
    media = "image/png" if name.lower().endswith(".png") else "application/octet-stream"
    return FileResponse(path, media_type=media)


@app.post("/reset")
async def reset_data(request: Request):
    """Clear master dataset and remove generated plots."""
    deleted_master = False
    if os.path.isfile(MASTER_DATA_PATH):
        try:
            os.remove(MASTER_DATA_PATH)
            deleted_master = True
        except Exception:
            deleted_master = False

    # Clear plots directory
    if os.path.isdir(PLOTS_DIR):
        for name in os.listdir(PLOTS_DIR):
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                try:
                    os.remove(os.path.join(PLOTS_DIR, name))
                except Exception:
                    pass

    result = {
        "status": "success",
        "message": "Data reset completed",
        "master_deleted": deleted_master,
    }
    log_action("reset", {"master_deleted": deleted_master})
    return result


@app.get("/login")
async def login_page(request: Request):
    return HTMLResponse(content="")


@app.get("/api/history")
async def api_history(limit: int = 50):
    items: List[dict] = []
    if os.path.isfile(ACTIONS_LOG_PATH):
        try:
            with open(ACTIONS_LOG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()[-limit:]
            import json
            for line in lines:
                try:
                    items.append(json.loads(line))
                except Exception:
                    pass
        except Exception:
            pass
    return {"status": "success", "items": items}


 


@app.post("/login")
async def login(request: Request, response: Response, username: str = Form(...), password: str = Form(...), role: str = Form("resident")):
    import os
    if role == "admin":
        admin_user = os.getenv("ADMIN_USER", "admin")
        admin_pass = os.getenv("ADMIN_PASS", "admin")
        if username != admin_user or password != admin_pass:
            return JSONResponse(status_code=401, content={"status": "error", "message": "Invalid admin credentials"})
    else:
        if not username or not password:
            return JSONResponse(status_code=401, content={"status": "error", "message": "Invalid credentials"})
    response.set_cookie(key="session_role", value=role, httponly=True)
    return {"status": "success", "role": role}


@app.post("/logout")
async def logout(response: Response):
    response.delete_cookie("session_role")
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)