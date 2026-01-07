# 1. Basic image

FROM continuumio/miniconda3

# 2. Maintainer

LABEL maintainer="Curtain"

# 3. Working directory

WORKDIR /app

# 4. Environmental dependence

COPY environment.yml /app/environment.yml
RUN conda env create -f environment.yml && conda clean -afy

# 5. [Repair points] Environment variables (added equal sign, removed non-existent variable references)


# First define the ISCE root directory

ENV ISCE_HOME="/opt/conda/envs/insar/share/isce2"
ENV ISCE_ROOT="/opt/conda/envs/insar/lib/python3.9/site-packages/isce"

# [Key Correction] Add ISCE’s applications directory to the front of PATH!
# In this way, the system can find topsApp.py

ENV PATH="$ISCE_ROOT/applications:/opt/conda/envs/insar/bin:$PATH"
ENV PATH="$ISCE_HOME/topsStack:$ISCE_ROOT/applications:/opt/conda/envs/insar/bin:$PATH"

# Python path

ENV PYTHONPATH="/opt/conda/envs/insar/lib/python3.9/site-packages"

ENV PROJ_LIB="/opt/conda/envs/insar/share/proj"

# 6. Copy the code

COPY code /app/code

# 7. Create a mount point

RUN mkdir -p /app/data

# Add entry script

COPY code/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Set entry point

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# 8. Default command

CMD ["python", "code/main_parallel.py"]