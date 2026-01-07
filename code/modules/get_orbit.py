import os
import subprocess
import sys
import glob
import shutil

def download_orbit(start_date, end_date, output_dir):
    """
    Download track file (Docker/Local universal version)
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # ---1. Smart skip logic (keep your logic) ---
    existing_files = glob.glob(os.path.join(output_dir, "*.EOF"))
    # Simple string matching may not be accurate, but it is enough for preliminary screening.
    # Note: The date in the track file name is usually V2023xxxx, which may differ by one day from start_date.
    # In order not to block the process here, first comment out the strict check, or only check the number of files.
    if len(existing_files) >= 2:
        print(f"   ✅ It is detected that the track directory already contains {len(existing_files)} files, skip downloading.")
        return os.path.abspath(output_dir)

    # ---2. Find dloadOrbits.py ---
    print(f"🛰️ Downloading track: {start_date} - {end_date}")

    # Supports explicitly specifying script paths through environment variables
    env_path = os.environ.get('DLOADORBITS_PATH')
    candidate = None
    if env_path:
        if os.path.exists(env_path):
            candidate = env_path
        else:
            print(f"⚠️ The path pointed to by the environment variable DLOADORBITS_PATH does not exist: {env_path}")

    # Prioritize using executable name (path) or candidate path
    names_to_try = []
    if candidate:
        names_to_try.append(candidate)
    names_to_try += ["dloadOrbits.py", "dloadOrbits"]

    # Search in some Conda/ISCE installation locations
    conda_common = [
        "/opt/conda/envs/insar/share/isce2/topsStack/dloadOrbits.py",
        "/opt/conda/envs/isce/share/isce2/topsStack/dloadOrbits.py",
        "/usr/local/share/isce2/topsStack/dloadOrbits.py",
        "/usr/share/isce2/topsStack/dloadOrbits.py",
    ]
    names_to_try += conda_common

    executable = None
    for name in names_to_try:
        # If it is a command name, try which
        if name in ("dloadOrbits.py", "dloadOrbits"):
            path = shutil.which(name)
            if path:
                executable = path
                break
            continue

        if os.path.exists(name):
            executable = name
            break

    if executable is None:
        print("⚠️ The dloadOrbits script (dloadOrbits.py) could not be found.")
        print("   Optional solutions:\n 1) Install ISCE/topsStack in the container/system;\n 2) Set the path of dloadOrbits.py to the environment variable DLOADORBITS_PATH;\n 3) Manually download the orbit file to data/orbit_data/.")
        print("   Note: dloadOrbits requires Earthdata (.netrc) credentials to generate access tokens, ensure the correct .netrc is mounted in the container. For example, at runtime, the host's netrc is mounted to /tmp/host_netrc and copied to /root/.netrc by entrypoint.sh.")
        return os.path.abspath(output_dir)

    # ---3. Execution ---
    # There is no need to add python_bin, because if executable is the command name, it can be run directly with shell=True.
    # python_bin is only needed if it is an absolute path and does not have execution permissions
    
    if os.path.isabs(executable) and executable.endswith('.py'):
        cmd = f"{sys.executable} {executable} --start {start_date} --end {end_date} --dir {output_dir}"
    else:
        # Directly call a command or executable script
        cmd = f"{executable} --start {start_date} --end {end_date} --dir {output_dir}"
    
    try:
        print(f"   -> Run command: {cmd}")
        subprocess.run(cmd, shell=True, check=True)
        print("   ✅ Track download executed successfully。")
    except subprocess.CalledProcessError as exc:
        print(f"   ⚠️ Orbital download command returns error: {exc}")
        print("   Please check that the network, Earthdata credentials (.netrc) are correct, or manually place the EOF file to data/orbit_data/。")
        # The process will not be interrupted. Subsequent steps will determine whether to continue based on the number of orbit files.
        
    return os.path.abspath(output_dir)