import os
import sys
import subprocess
import requests
import time
from osgeo import gdal

# ==============================================================================
# Configuration area
# ==============================================================================
MAX_RETRIES = 5        # Maximum number of download retries
RETRY_DELAY = 10       # Number of seconds to wait after failure (will increase with the number of times)
DOWNLOAD_TIMEOUT = 180 # Download timeout (seconds)

def write_isce_xml(dem_path, width, length, first_lat, first_lon, delta_lat, delta_lon):
    """
    Manually write ISCE XML (standard factory mode version)
    """
    file_name = os.path.basename(dem_path)
    xml_path = dem_path + ".xml"
    
    print(f"   -> ✍️ Generating standard version XML: {file_name}.xml")
    
    # The key here is:
    # 1. Component must contain factorymodule and factoryname
    # 2. The attribute names strictly correspond to (startingValue, delta, size)
    # 3. Quote EGM96
    # 4. Only write relative paths in file names
    
    xml_content = f"""<imageFile>
    <property name="width">
        <value>{width}</value>
    </property>
    <property name="length">
        <value>{length}</value>
    </property>
    <property name="access_mode">
        <value>read</value>
    </property>
    <property name="byte_order">
        <value>l</value>
    </property>
    <property name="data_type">
        <value>FLOAT</value>
    </property>
    <property name="image_type">
        <value>dem</value>
    </property>
    <property name="file_name">
        <value>{file_name}</value>
    </property>
    <property name="reference">
        <value>EGM96</value>
    </property>
    <component name="coordinate1">
        <factorymodule>isceobj.Image</factorymodule>
        <factoryname>createCoordinate</factoryname>
        <property name="name">
            <value>longitude</value>
        </property>
        <property name="size">
            <value>{width}</value>
        </property>
        <property name="startingValue">
            <value>{first_lon}</value>
        </property>
        <property name="delta">
            <value>{delta_lon}</value>
        </property>
    </component>
    <component name="coordinate2">
        <factorymodule>isceobj.Image</factorymodule>
        <factoryname>createCoordinate</factoryname>
        <property name="name">
            <value>latitude</value>
        </property>
        <property name="size">
            <value>{length}</value>
        </property>
        <property name="startingValue">
            <value>{first_lat}</value>
        </property>
        <property name="delta">
            <value>{delta_lat}</value>
        </property>
    </component>
</imageFile>
"""
    with open(xml_path, "w") as f:
        f.write(xml_content)
    
    print(f"   ✅ XML generated successfully")

def generate_xml_metadata(dem_path):
    """Reading information through GDAL and calling XML writing functions"""
    ds = gdal.Open(dem_path)
    if not ds:
        raise Exception(f"Unable to open file for reading metadata: {dem_path}")
    
    width = ds.RasterXSize
    length = ds.RasterYSize
    geo_transform = ds.GetGeoTransform()
    # geo_transform: (left_lon, lon_res, 0, top_lat, 0, lat_res)
    first_lon = geo_transform[0] + geo_transform[1]/2.0
    first_lat = geo_transform[3] + geo_transform[5]/2.0
    delta_lon = geo_transform[1]
    delta_lat = geo_transform[5]
    
    write_isce_xml(dem_path, width, length, first_lat, first_lon, delta_lat, delta_lon)
    ds = None

def download_dem(south, north, west, east, output_dir, source=1, api_key=None):
    """
    Core download and conversion logic
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Define file name
    base_name = f"demLat_N{int(north)}_S{int(south)}_W{int(west)}_E{int(east)}"
    dem_path = os.path.join(output_dir, base_name + ".wgs84")
    tif_path = os.path.join(output_dir, "temp_download.tif")
    vrt_path = dem_path + ".vrt"

    # If it is found that tif already exists but the conversion fails, force delete and re-install.
    if os.path.exists(tif_path):
        # Check the file size, if it is too small (for example, less than 1MB), it is basically bad.
        if os.path.getsize(tif_path) < 1024 * 1024:
            print("⚠️ The remaining DEM file detected is too small and may be damaged. Delete and re-download...")
            os.remove(tif_path)

    # ---1. Existence check (avoid duplication of work) ---
    if os.path.exists(dem_path) and os.path.exists(dem_path + ".xml"):
        print(f"   ✅ DEM already exists: {base_name}, skip downloading.")
        if not os.path.exists(vrt_path):
            subprocess.run(f"gdal_translate -of VRT {dem_path} {vrt_path}", shell=True)
        return os.path.abspath(dem_path)

    # ---2. Download logic (with retry mechanism) ---
    # If the user manually puts a temp_download.tif there, the script will also recognize it and continue the conversion
    if not os.path.exists(tif_path):
        if not api_key:
            raise ValueError("❌ Error: DEM download required but OpenTopography API Key not provided!")

        demtype = "SRTMGL1" if source == 1 else "SRTMGL3"
        url = "https://portal.opentopography.org/API/globaldem"
        params = {
            "demtype": demtype,
            "south": south, "north": north, "west": west, "east": east,
            "outputFormat": "GTiff", "API_Key": api_key,
        }

        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"   ⬇️ Downloading DEM (try {attempt}/{MAX_RETRIES})...")
                with requests.get(url, params=params, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
                    r.raise_for_status()
                    with open(tif_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024*1024): # 1MB chunk
                            if chunk: f.write(chunk)
                
                # Verification: Check the file size. Open topo errors sometimes return small text.
                if os.path.getsize(tif_path) < 5000: # Less than 5 kb is definitely wrong
                    with open(tif_path, 'r', errors='ignore') as f:
                        error_msg = f.read(200)
                    print(f"   ⚠️ The server returns exception information:{error_msg}")
                    raise Exception("Download file is invalid")

                success = True
                break
            except Exception as e:
                print(f"   ❌ {attempt} download failed: {e}")
                if attempt < MAX_RETRIES:
                    wait = attempt * RETRY_DELAY
                    print(f"   ⏳ {wait} Try again in seconds...")
                    time.sleep(wait)
        
        if not success:
            raise Exception("❌ If you still cannot download the DEM after several attempts, please check the network or API Key validity.")

    # ---3. Format conversion (Tiff -> ISCE ENVI) ---
    print("   🔄 Converting to ISCE standard format (Float32)...")
    try:
        # Use -a_nodata 0 to handle valueless areas, -ot Float32 to ensure accuracy
        cmd_trans = f"gdal_translate -of ENVI -ot Float32 -a_nodata 0 {tif_path} {dem_path}"
        subprocess.check_call(cmd_trans, shell=True)
        
        # Force VRT generation
        subprocess.check_call(f"gdal_translate -of VRT {dem_path} {vrt_path}", shell=True)
        
        # Generate XML
        generate_xml_metadata(dem_path)
        
    except Exception as e:
        if os.path.exists(dem_path): os.remove(dem_path) # Conversion failed to clean up the residue
        raise Exception(f"❌ Format conversion or metadata generation failed: {e}")
    finally:
        # ---4. Clean up temporary files ---
        if os.path.exists(tif_path): os.remove(tif_path)
        if os.path.exists(dem_path + ".hdr"): os.remove(dem_path + ".hdr")

    print(f"   🎉 DEM ready:{dem_path}")
    return os.path.abspath(dem_path)
