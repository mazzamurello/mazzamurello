# The sandbox image (ADR-0053): where the agent's commands run, under gVisor.
# It holds no credentials (SBX-008) and runs nothing until the driver execs
# commands in it.
FROM debian:13.2-slim

# Nothing a sandbox uses is left out (ADR-0080): package documentation, and
# the GPU drivers that Debian's ffmpeg depends on but loads only with a GPU,
# which a sandbox does not have.
RUN printf '%s\n' \
        'path-exclude=/usr/share/doc/*' 'path-include=/usr/share/doc/*/copyright' \
        'path-exclude=/usr/share/man/*' 'path-exclude=/usr/share/info/*' \
        'path-exclude=/usr/lib/*/libLLVM*' 'path-exclude=/usr/lib/*/libgallium*' \
        'path-exclude=/usr/lib/*/libz3.so*' 'path-exclude=/usr/lib/*/dri/*' \
        'path-exclude=/usr/lib/*/libvulkan_*' \
        > /etc/dpkg/dpkg.cfg.d/mazzamurello-sandbox

# The toolbox for a household's files (SBX-021, ADR-0080): documents and
# their fonts, images and media, data, and Node.js.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash ca-certificates coreutils curl git iproute2 procps python3 python3-venv \
        poppler-utils qpdf pandoc fontconfig fonts-dejavu-core fonts-liberation fonts-noto-core \
        imagemagick ffmpeg \
        jq sqlite3 file zip unzip \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

# npm from its own release, which bundles what it needs, instead of Debian's
# hundreds of packages; checked against the registry's sha512.
ARG NPM_VERSION=10.9.9
ARG NPM_SHA512=d60fba8cb42f688b81e33c2f1cbef2ad7b977166700ec0ad057f1b6d60ea6ef2524abf673e20c35931cd8305d1dbb8887134d6eefdc0e7b8435bd458bf65b862
RUN curl -fsSL "https://registry.npmjs.org/npm/-/npm-${NPM_VERSION}.tgz" -o /tmp/npm.tgz \
    && echo "${NPM_SHA512}  /tmp/npm.tgz" | sha512sum -c - \
    && mkdir -p /usr/local/lib/node_modules/npm \
    && tar -xzf /tmp/npm.tgz -C /usr/local/lib/node_modules/npm --strip-components=1 \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && rm /tmp/npm.tgz

# The Python of the agent's work, first on the PATH: office files, Markdown
# for the model, tables and charts, pinned by hash and from wheels only.
COPY deploy/images/sandbox/tools-requirements.txt /opt/tools-requirements.txt
RUN python3 -m venv /opt/tools \
    && /opt/tools/bin/pip install --no-cache-dir --require-hashes --only-binary :all: \
        -r /opt/tools-requirements.txt \
    && rm /opt/tools-requirements.txt \
    && find /opt/tools/lib -depth -type d -name tests -exec rm -rf {} +
ENV PATH=/opt/tools/bin:$PATH

# The page reader of read_page (AGT-021, ADR-0075), with its dependencies
# pinned by hash, in an environment of its own.
COPY deploy/images/sandbox/reader-requirements.txt /opt/reader-requirements.txt
RUN python3 -m venv /opt/reader \
    && /opt/reader/bin/pip install --no-cache-dir --require-hashes --only-binary :all: \
        -r /opt/reader-requirements.txt \
    && rm /opt/reader-requirements.txt
COPY --chmod=0755 deploy/images/sandbox/mzm-read-page /usr/local/bin/mzm-read-page

# Commands start in the scratch folder; only /workspace persists (ADR-0076).
RUN mkdir -p /scratch /workspace
WORKDIR /scratch
CMD ["sleep", "infinity"]
