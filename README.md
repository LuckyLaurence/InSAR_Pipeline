# Parallel InSAR Pipeline with Docker & ISCE2
![Python](https://img.shields.io/badge/Python-3.9-blue)
![ISCE2](https://img.shields.io/badge/ISCE-2.6.3-orange)
![Docker](https://img.shields.io/badge/Docker-Containerized-blueviolet)
![Status](https://img.shields.io/badge/Status-Stable-green)

An automated, containerized, and parallel processing pipeline for Interferometric Synthetic Aperture Radar (InSAR) processing based on **ISCE2** (topsApp).

Designed to handle large-scale Sentinel-1 datasets efficiently by leveraging Python multiprocessing and Docker isolation.

## 🚀 Key Features

*   **Parallel Processing**: Built-in process pool scheduler (`multiprocessing`) to handle multiple Interferogram pairs simultaneously.
*   **Dockerized Environment**: Zero-dependency deployment. Runs anywhere (Linux, Windows/WSL2, Cloud) with Docker.
*   **Auto-Provisioning**:
    *   Automated DEM download from OpenTopography (with on-the-fly XML/VRT generation).
    *   Automated Orbit files download from ASF.
*   **Robustness**:
    *   **Phase-Split Execution**: Smartly handles ISCE step dependencies to enable checkpoint restart (e.g., skipping `ion` step in memory).
    *   **Fault Tolerance**: Automatic retry logic for unstable steps and task isolation (one task failure doesn't stop the pipeline).
*   **Storage Optimized**: "Nuclear" cleaning scripts to minimize disk usage by 90% after processing.

## 📂 Project Structure

```text
InSAR_Pipeline/
├── Dockerfile              # Docker build configuration
├── run_docker.sh           # One-click startup script
├── .env.example            # set your API_KEY，delete`.example`
├── environment.yml         # python site-packages
├── code/
│   ├── main_parallel.py    # Main scheduler & processor
│   ├── modules/            # Helper modules (DEM, Orbit, XML)
│   └── entrypoint.sh       # support utilities
└── data/                   # Data directory (Mounted volume)
    ├── raw/                # Sentinel-1 SLC data (.SAFE)
    ├── orbit_data/         # Sentinel-1 Orbit data (.EOF)
    ├── dem/                # DEM storage
    └── runs/               # Processing outputs
    pairs.txt               # target pairs
```

## 🛠️ Getting Started
### Prerequisites
- Docker Desktop (Windows/Mac) or Docker Engine (Linux)
- OpenTopography API Key
### 1. Setup Data
Place your Sentinel-1 SLC data into `data/raw`.

### 2. Configure Pipeline
Edit `pairs.txt` to set your target pairs:
```txt
("S1A_...20230203...SAFE", "S1A_...20230215...SAFE")
("S1A_...20230215...SAFE", "S1A_...20230227...SAFE")
("S1A_...20230203...SAFE", "S1A_...20230227...SAFE")
```
Put a pair of pairs on one line, and then jump

Edit `.env` to set your target pairs:
```
OPENTOPO_API_KEY=your API
ROI=38.0,41.0,33.0,38.0  # Set the range of downloaded DEM
WORKERS = 2  # Set based on your RAM (rec: 16GB per worker)
```
### 3. Run with Docker
Execute the startup script. It will mount your local data and code into the container.
```Bash
chmod +x run_docker.sh
./run_docker.sh
```
## 📊 Results
### Interferogram (Wrapped Phase)
Interferogram

see the `results_sample/Interferogram`

### Unwrapped Phase
Unwrapped

see the `results_sample/Unwrapped Phase`

## 📝 License
This project is open-sourced under the MIT License.