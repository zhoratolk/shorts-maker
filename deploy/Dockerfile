# The personal pipeline, packaged so it runs on the server instead of the desktop.
#
# Its own image on purpose. The business service on this machine builds from the same
# public base, and that is where the similarity ends: sharing a built image would mean a
# rebuild on one side quietly changing the behaviour of the other, which is exactly the
# coupling both projects are meant not to have. They share hardware, not software.
#
# Same base tag as the business image because this box has already proven it: cp312
# wheels for the whole torch/ctranslate2 stack, ffmpeg 6.1 with NVENC, and a CUDA 12.x
# runtime that runs under this host's 595 driver.
FROM nvidia/cuda:12.9.2-cudnn-runtime-ubuntu24.04

# NVENC and NVDEC sit behind the `video` driver capability, which the CUDA base images
# do not request (they ask for compute,utility). On this host's toolkit the encoder
# libraries get mounted either way - it uses CDI, which ignores this variable - but the
# declaration is the documented contract and costs nothing.
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ffmpeg \
        fonts-dejavu-core fonts-liberation \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Debian marks the system Python as externally managed, and there is nothing else in this
# image to protect it from.
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# The two Windows faces the clips are rendered with. Copied in rather than substituted:
# the banner and subtitle styling is the channel's look, and Liberation or DejaVu at the
# same size reads visibly lighter. Both carry full Cyrillic coverage.
COPY deploy/fonts/*.ttf /usr/share/fonts/truetype/msfonts/
RUN fc-cache -f

WORKDIR /app

# Dependencies before the code, so editing a script does not re-download several
# gigabytes of torch and CUDA wheels. The extras are named explicitly rather than
# installed through `.[all]` because that form needs the project itself present, which
# would drag the code into this layer and defeat the split.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        "pyannote.audio>=3.1" \
        "opencv-python-headless>=4.8" \
        "librosa>=0.10" \
        "google-api-python-client>=2.100" \
        "google-auth-oauthlib>=1.2" \
        "google-auth-httplib2>=0.2"

# yt-dlp last, after the heavy wheels, and in a layer of its own. It is unpinned on
# purpose - a rebuild is how it learns about the player change that broke yesterday's
# download - so it is the line most likely to be invalidated, and every layer after an
# invalidated one is rebuilt too. Ahead of the torch install it would have made
# refreshing a two-megabyte downloader cost a re-fetch of several gigabytes of CUDA.
RUN pip install --no-cache-dir yt-dlp

COPY . .
RUN pip install --no-cache-dir --no-deps -e .

CMD ["python3", "-c", "print('give me a command: scripts/ingest.py or scripts/render_batch.py')"]
