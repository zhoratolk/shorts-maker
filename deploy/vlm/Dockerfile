# The pipeline image plus what a vision-language model needs at runtime.
#
# Two additions, both for the same reason. transformers ships triton kernels that are
# compiled on first use, and the base image has no C compiler ("Failed to find C
# compiler"); and the visual processor needs torchvision, which the pipeline never did.
#
# Installed into the image rather than into the mounted cache: a --target install put a
# second torch on the path that shadowed the image own, and the wheels are built for the
# container Python, so they cannot be shared with the host (3.14) either.
FROM shorts-maker:latest
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir "transformers>=5.0" accelerate torchvision
