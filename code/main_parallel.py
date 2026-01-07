#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from multiprocessing import Pool
import glob
import logging
import shutil
import datetime
import re

# ===========================================
# ISCE prevents all nuclear weapons from being used lethally
# Construction location 4 or 8
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"
# ==========================================

# ---Path configuration ---
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CODE_DIR)

RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
DEM_DIR = os.path.join(PROJECT_ROOT, "data", "dem")
ORBIT_DIR = os.path.join(PROJECT_ROOT, "data", "orbit_data")
RUNS_DIR = os.path.join(PROJECT_ROOT, "data", "runs")

sys.path.append(CODE_DIR)
from modules.get_dem import download_dem
from modules.get_orbit import download_orbit

# Retry tool, which is used to retry when the execution of the command fails.
def run_with_retry(cmd, cwd=None, retries=2, delay=3, shell=True):
    for attempt in range(1, retries + 1):
        try:
            subprocess.run(cmd, shell=shell, check=True, cwd=cwd)
            return True
        except subprocess.CalledProcessError as e:
            if attempt < retries:
                logging.warning(f"⚠️ Retry on failure ({attempt}/{retries}): {cmd}")
                time.sleep(delay)
            else:
                raise e

# Used to clean up the pickle cache folder in the ISCE running directory
def cleanup_pickles(target_dir):
    try:
        if os.path.exists(os.path.join(target_dir, "pickle")):
            shutil.rmtree(os.path.join(target_dir, "pickle"))
    except: pass

# The function is to extract the date range from PAIRS for downloading track files
def get_date_range_from_pairs(pairs):
    """
    Traverse all PAIRS, parse the date in the file name, and return (earliest date, latest date)
    Format: YYYYMMDD
    """
    dates = []
    for ref, sec in pairs:
        # SAFE file name format: S1A_IW_SLC__1SDV_20230203T...
        # split('_')[5] gets 20230203T034221
        try:
            d1 = ref.split('_')[5][:8]
            d2 = sec.split('_')[5][:8]
            dates.append(d1)
            dates.append(d2)
        except IndexError:
            print(f"⚠️ Unable to parse filename date: {ref} 或 {sec}")
            continue
    
    if not dates:
        # If parsing fails, give a default conservative value or report an error
        return None, None

    # Sort to find min and max
    dates.sort()
    start_date = dates[0]
    end_date = dates[-1]

    return start_date, end_date    

# General soft link function
def atomic_link(src, dst):
    """
    True atomic soft link:
    1. src: original file path (such as data/dem/dem.wgs84)
    2. dst: target link path (such as data/runs/run_xxx/dem.wgs84)
    """
    # Step 1: Physically check whether the source file exists. It is useless if the link does not exist.
    if not os.path.exists(src):
        print(f"❌ Link failed: source file does not exist -> {src}")
        return False

    # Step 2: If there is already something in the target location (whether it is a dead link or an old file), kill it directly.
    if os.path.lexists(dst): 
        os.remove(dst)

    # Step 3: Create soft links (prefer using relative paths to improve portability)
    try:
        rel_src = os.path.relpath(src, os.path.dirname(dst))
        os.symlink(rel_src, dst)
        if os.path.islink(dst):
            print(f"   -> Symbolic link created: {dst} -> {rel_src}")
            return True
        else:
            print(f"❌ Not created as a symbolic link (unknown reason): {dst}")
            return False
    except Exception as e:
        print(f"❌ Soft link creation exception: {e}")
        return False

# Parse pairs.txt
def load_pairs_from_file(file_path):
    pairs_list = []
    if not os.path.exists(file_path):
        return []
    
    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            found = re.findall(r"S1[AB]_IW_SLC__[0-9A-Za-zT_\-]+\.SAFE", line)
            if len(found) == 2:
                pairs_list.append((found[0], found[1]))
                continue

            cleaned = line.strip().lstrip('(').rstrip(')').strip()
            # Replace Chinese or redundant separators
            cleaned = cleaned.replace('\"', '"')
            if ',' in cleaned:
                parts = [p.strip().strip('"').strip("'") for p in cleaned.split(',') if p.strip()]
            else:
                parts = [p.strip().strip('"').strip("'") for p in cleaned.split() if p.strip()]

            if len(parts) == 2:
                pairs_list.append((parts[0], parts[1]))
            else:
                print(f"⚠️ Ignore malformed lines: {line}")
    return pairs_list

def get_s1_date(safe_name):
    """
   Robust extraction of dates (YYYYMMDD) from Sentinel-1 filenames
    """
    try:
        match = re.search(r"(\d{8})T\d{6}", safe_name)
        if match:
            return match.group(1)
        return "UnknownDate"
    except:
        return "Error"
    
# =================== Configuration area ====================
API_KEY =  os.environ.get("OPENTOPO_API_KEY") # Read API Key from environment variable
DEM_BASE_NAME = os.environ.get("DEM_BASENAME","dem_standard")

# Possible ROI formats in parsed environment variables: "south,north,west,east" or "[s,n,w,e]"
roi_env = os.environ.get('ROI')

if roi_env:
    try:
        cleaned = roi_env.strip().lstrip('[').rstrip(']').strip()

        cleaned = cleaned.replace(';', ',').replace(' ', ',')
        parts = [p for p in cleaned.split(',') if p != '']
        if len(parts) == 4:
            ROI = tuple(float(x) for x in parts)
        else:
            print(f"⚠️ Unable to parse ROI environment variable (expected 4 values)：{roi_env}")
    except Exception as e:
        print(f"⚠️ Error parsing ROI: {e}")
        
# Data list name
DEFAULT_PAIRS_FILE = os.path.join(PROJECT_ROOT, "data", "pairs.txt")

WORKERS = int(os.environ.get("WORKERS", 2)) # Default 2
START_STEP = 'startup' # must start from scratch

# ==================================================

def prepare_shared_resources(custom_name):
    # ---------------------------------------------------------
    # 1. DEM preparation (existing logic remains unchanged)
    # ---------------------------------------------------------
    print("🔍 [Phase 1] Check/Download DEM...")
    # Dynamically piece together filenames
    target_dem = os.path.join(DEM_DIR, f"{custom_name}.wgs84")
    
    # If the file already exists and is intact, return the absolute path directly.
    if os.path.exists(target_dem) and os.path.exists(target_dem + ".xml") and os.path.exists(target_dem + ".vrt"):
        print(f"✅ Existing DEM detected: {target_dem}")
        return target_dem

    # If it does not exist, call the download logic
    print(f"🌐 Downloading new DEM for project [{custom_name}]...")
    # If ROI (south,north,west,east) is provided and API_KEY is provided, then attempts to download the DEM
    if ROI and API_KEY:
        try:
            south, north, west, east = ROI
            print(f"   ->Download DEM using ROI: S={south}, N={north}, W={west}, E={east}")
            downloaded = download_dem(south, north, west, east, DEM_DIR, api_key=API_KEY)
            # download_dem returns the absolute path
            target_dem = downloaded
            print(f"   -> DEM downloaded and ready: {target_dem}")
            # Verify that the generated metadata file exists (to avoid subsequent ISCE verifyDEM failures)
            if not os.path.exists(target_dem + ".xml") or not os.path.exists(target_dem + ".vrt"):
                print("❌DEM download or conversion does not generate required metadata files（.xml/.vrt）")
                print(f"   ->Current {DEM_DIR} list:")
                for fn in sorted(os.listdir(DEM_DIR)):
                    print(f"      - {fn}")
                raise Exception("The DEM file is missing supporting metadata (.xml/.vrt). Please check that GDAL(gdal_translate) and the osgeo Python bindings are installed in the container, or view the download log for get_dem.py.")
        except Exception as e:
            print(f"⚠️ DEM download failed: {e}")
    else:
        if not ROI:
            print("⚠️ No ROI set, automatic download of DEM skipped. Please set ROI in .env or place dem file manually。")
        if not API_KEY:
            print("⚠️ OPENTOPO_API_KEY is not set, DEM cannot be downloaded automatically。")
     
    # ---------------------------------------------------------
    # 2. Track preparation ([Core modification]: changed from checking only to automatic downloading)
    # ---------------------------------------------------------
    print(f"🔍 [Phase 1] Check/download orbital files at: {ORBIT_DIR}")
    
    # 2.1 Calculate the required date range (read from pairs file)
    pairs = load_pairs_from_file(DEFAULT_PAIRS_FILE)
    start_date, end_date = get_date_range_from_pairs(pairs)
    if not start_date:
        print("⚠️ Unable to parse date from PAIRS, skip track auto-download, only check existing files。")
    else:
        # 2.2 For insurance, push the start forward by 1 day (date calculation in Python is more complicated, so it is simply handled here)

        print(f"   -> Identify image time range: {start_date} 至 {end_date}")
        
        # [Call get_orbit.py here]
        # To prevent corrupted files of only a few MB, clean the empty folders first, or trust the overwriting mechanism of dloadOrbits
        download_orbit(start_date, end_date, ORBIT_DIR)

    # 2.3 Check the download results again
    eof_files = glob.glob(os.path.join(ORBIT_DIR, "*.EOF")) + glob.glob(os.path.join(ORBIT_DIR, "*.eof"))
    if len(eof_files) < 2:
        print("⚠️ Warning: The number of track files is very small (<2), ISCE may report an error!")
        print("   -> Please check whether the network can connect to NASA orbital server, or download manually。")
    else:
        print(f"✅Orbital data prepared, total {len(eof_files)} files。")
    
    # Returns the absolute path to the DEM (the main process expects a single return value)
    return os.path.abspath(target_dem)

def link_orbits_to_run_dir(run_dir, orbit_source_dir):
    """
    [Core Repair] Soft link (or copy) all track files to the running directory
    ISCE will find the appropriate one in the current directory.
    """
    print(f"   -> Linking track files to{os.path.basename(run_dir)} ...")
    source_files = glob.glob(os.path.join(orbit_source_dir, "*.EOF")) + glob.glob(os.path.join(orbit_source_dir, "*.eof"))
    
    for src in source_files:
        filename = os.path.basename(src)
        dst = os.path.join(run_dir, filename)
        
        # In the internal environment of the container (linux), soft links are very stable
        if os.path.lexists(dst):
            os.remove(dst)
        os.symlink(src, dst)

def generate_xml(run_dir, ref_name, sec_name, dem_full_path):
    """
    All paths pass [file name] because they have been linked to run_dir by atomic_link
    """ 
    # Use basename as demFilename to ensure that ISCE looks for local link files in the running directory
    dem_basename = os.path.basename(dem_full_path)
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<topsApp>
<component name="topsinsar">
<property name="sensor name">SENTINEL1</property>
<property name="swaths">[1,2,3]</property>
<property name="do unwrap">True</property>
<property name="unwrapper name">snaphu_mcf</property>
<property name="demFilename">{dem_basename}</property>
<component name="reference">
<property name="output directory">master</property>
<property name="safe">{ref_name}</property>
</component>
<component name="secondary">
<property name="output directory">slave</property>
<property name="safe">{sec_name}</property>
</component>
</component>
</topsApp>
"""
    with open(os.path.join(run_dir, "topsApp.xml"), "w") as f:
        f.write(xml_content)

def worker_task(args):
    ref_name, sec_name, dem_path = args
     
    # Run directory naming: run_primary image date_secondary image date
    try:
        ref_date = ref_name.split('_')[5][:8]
        sec_date = sec_name.split('_')[5][:8]
        folder_name = f"run_{ref_date}_{sec_date}"
    except:
        folder_name = f"run_{ref_name[:10]}_{sec_name[:10]}"

    # Create a run directory named run_YYYYMMDD_YYYYMMDD
    run_dir = os.path.join(RUNS_DIR, folder_name)
    if not os.path.exists(run_dir): os.makedirs(run_dir)
    
    log_prefix = f"[{folder_name}]"
    print(f"{log_prefix} 🚀 start up...")
    
    # 1. Prepare link track (ORBIT_DIR -> run_dir)
    orbit_files = glob.glob(os.path.join(ORBIT_DIR, "*.EOF"))
    for eof in orbit_files:
        atomic_link(eof, os.path.join(run_dir, os.path.basename(eof)))

    # Link the DEM to the running directory (ISCE usually looks for the DEM and its .xml/.vrt in the current directory)
    try:
        if dem_path:
            for ext in ["", ".xml", ".vrt"]:
                src = dem_path + ext
                if os.path.exists(src):
                    atomic_link(src, os.path.join(run_dir, os.path.basename(src)))
                else:
                    print(f"   ⚠️ DEM related files are missing: {src}")
    except Exception as e:
        print(f"   ⚠️ Error linking DEM to run directory: {e}")

    # 2. Prepare to link the original image (RAW_DIR -> run_dir)
    atomic_link(os.path.join(RAW_DIR, ref_name), os.path.join(run_dir, ref_name))
    atomic_link(os.path.join(RAW_DIR, sec_name), os.path.join(run_dir, sec_name))
       
    print(f"{log_prefix} 🔗 Both images and tracks are linked to the sandbox, and the DEM uses a shared absolute path")
    
    # 2. Generate XML 
    generate_xml(run_dir, ref_name, sec_name, dem_path)
    
    # 3. Clear cache
    if START_STEP == 'startup':
        cleanup_pickles(run_dir)

    # 4. Segmented execution strategy
    PHASE_1 = ['startup', 'preprocess', 'computeBaselines', 'verifyDEM', 'topo',
               'subsetoverlaps', 'coarseoffsets', 'coarseresamp', 'overlapifg', 
               'prepesd', 'esd', 'rangecoreg', 'fineoffsets']
    
    # Initialize task timing
    task_start_time = time.time()

    try:
        # 1. Execute Phase 1
        current_steps = []
        if START_STEP in PHASE_1:
            start_idx = PHASE_1.index(START_STEP)
            current_steps = PHASE_1[start_idx:]
        
        # Loop execution Phase 1
        for step in current_steps:
            step_start = time.time()  # <---Timing starts
            print(f"{log_prefix} -> {step}")
            
            cmd = f"topsApp.py topsApp.xml --steps --start={step} --end={step}"
            run_with_retry(cmd, cwd=run_dir, retries=2)
            
            # <---Timing ends & printing time---
            step_cost = time.time() - step_start
            print(f"{log_prefix} ✅ {step} Finish ({step_cost:.1f}s)")

        # 2. Execute Phase 2 (key! Complete it in one go)
        print(f"{log_prefix} -> 🚀 Entering Phase 2 (continuous execution, across ions)...")
        p2_start = time.time() # <---Phase 2 timing starts
        
        PHASE_2_START = "fineresamp"
        PHASE_2_END = "geocode"
        cmd_phase2 = f"topsApp.py topsApp.xml --steps --start={PHASE_2_START} --end={PHASE_2_END}"
        run_with_retry(cmd_phase2, cwd=run_dir, retries=1, delay=5)
        
        p2_cost = (time.time() - p2_start) / 60 # <---Phase 2 timer ends (minutes)
        print(f"{log_prefix} ✅ Phase 2 Finish ({p2_cost:.2f} min)")
            
        total_cost = (time.time() - task_start_time) / 60
        return f"{log_prefix} 🎉 Success! Total time taken: {total_cost:.2f} min"
        
    except Exception as e:
        return f"{log_prefix} ❌ fail: {e}"

def main():
    print(f"🕒 Start time: {datetime.datetime.now().strftime('%H:%M:%S')}")
    
    # ---1. Check environment variables ---
    if not API_KEY:
        print("❌ Error: OPENTOPO_API_KEY not detected, please check .env")
        sys.exit(1)

    # ---2. Load and print tasks ---
    PAIRS = load_pairs_from_file(DEFAULT_PAIRS_FILE)
    print("\n" + "="*60)
    print(f"📋 Task List (Parallelism: {WORKERS})")
    for i, (m, s) in enumerate(PAIRS):
        m_date = get_s1_date(m)
        s_date = get_s1_date(s)
        # Printing effect: [Task 1]: 20230215 vs 20230227
        print(f"   👉 [Task {i+1}]: {m_date} vs {s_date}")
    print("="*60 + "\n")

    # ---3. Prepare resources ---
    try:
        print("🔧 Preparing shared resources (DEM and orbit)...")
        dem_path = prepare_shared_resources(custom_name=DEM_BASE_NAME)
    except Exception as e:
        print(f"❌ Resource preparation failed: {e}")
        sys.exit(1)

    # ---4. Build process pool parameters ---
    task_args = []
    for m, s in PAIRS:
        task_args.append((m, s, dem_path))

    # ---5. Execute parallel tasks ---
    print(f"🚀 Starting parallel computation (using {WORKERS} Workers)...")
    with Pool(WORKERS) as pool:
        results = pool.map(worker_task, task_args)

    print("\n📊 Summary of results:")
    for res in results:
        print(res)
    
    print(f"🕒 End: {datetime.datetime.now().strftime('%H:%M:%S')}")

if __name__ == "__main__":
    main()