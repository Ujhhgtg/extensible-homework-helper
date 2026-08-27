default:
    just --list

alias b := build

build:
    uv build
    @echo "build complete. distribution file is at dist/ehh-0.0.1-py3-none-any.whl"

alias i := install

install:
    uv tool install .

alias r := run-repl

run-repl:
    @echo "running ehh repl"
    uv run ehh-repl

run-bot:
    @echo "running ehh telegram bot"
    uv run ehh-tgbot

install-torch-cu126:
    uv tool install . --with torch --with torchvision --index-url https://download.pytorch.org/whl/cu126
    @echo "installed torch with CUDA 12.6 support"

install-torch-cu128:
    uv tool install . --with torch --with torchvision
    @echo "installed torch with CUDA 12.8 support"

install-torch-cu130:
    uv tool install . --with torch --with torchvision --index-url https://download.pytorch.org/whl/cu130
    @echo "installed torch with CUDA 13.0 support"

install-torch-rocm72:
    uv tool install . --with torch --with torchvision --index-url https://download.pytorch.org/whl/rocm7.2
    @echo "installed torch with ROCm 7.2 support"

install-torch-cpu:
    uv tool install . --with torch --with torchvision --index-url https://download.pytorch.org/whl/cpu
    @echo "installed torch with CPU support"
