default:
    just --list

alias b := build

# build wheel
build:
    uv build
    @echo "build complete. distribution file is at dist/ehh-0.0.1-py3-none-any.whl"

alias i := install

# install package
install:
    uv tool install .

alias r := run-repl

# run repl
run-repl:
    @echo "running ehh repl"
    ehh-repl

# run telegram bot
run-bot:
    @echo "running ehh telegram bot"
    ehh-tgbot

# install pytorch with cuda 12.6 support
install-torch-cu126:
    uv tool install . --with torch --with torchvision --index-url https://download.pytorch.org/whl/cu126
    @echo "installed torch with CUDA 12.6 support"

# install pytorch with cuda 12.8 support
install-torch-cu128:
    uv tool install . --with torch --with torchvision
    @echo "installed torch with CUDA 12.8 support"

# install pytorch with cuda 13.0 support
install-torch-cu130:
    uv tool install . --with torch --with torchvision --index-url https://download.pytorch.org/whl/cu130
    @echo "installed torch with CUDA 13.0 support"

# install pytorch with rocm 7.1 support
install-torch-rocm71:
    uv tool install . --with torch --with torchvision --index-url https://download.pytorch.org/whl/rocm7.1
    @echo "installed torch with ROCm 7.1 support"

# install pytorch with rocm 7.1 support
install-torch-cpu:
    uv tool install . --with torch --with torchvision --index-url https://download.pytorch.org/whl/cpu
    @echo "installed torch with CPU support"
