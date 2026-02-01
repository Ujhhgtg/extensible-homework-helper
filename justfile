default:
    just --list

alias b := build

# build wheel
build:
    uv build
    @echo "build complete. distribution files are in dist/"

alias i := install

# install package
install:
    uv pip install ./dist/*.tar.gz
    @echo "installation complete"

alias r := run-repl

# run repl
run-repl:
    @echo "running ehh repl"
    uv run python -m ehh.repl

# run telegram bot
run-bot:
    @echo "running ehh telegram bot"
    uv run python -m ehh.telegram_bot

# run custom
run NAME:
    @echo "running ehh {{NAME}}"
    uv run python -m ehh.{{NAME}}

# install pytorch with cuda 12.6 support
install-torch-cu126:
    uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126 --force-reinstall
    @echo "installed torch with CUDA 12.6 support"

# install pytorch with cuda 12.8 support
install-torch-cu128:
    uv pip install torch torchvision --force-reinstall
    @echo "installed torch with CUDA 12.8 support"

# install pytorch with cuda 13.0 support
install-torch-cu130:
    uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130 --force-reinstall
    @echo "installed torch with CUDA 13.0 support"

# install pytorch with rocm 7.1 support
install-torch-rocm71:
    uv pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm7.1 --force-reinstall
    @echo "installed torch with ROCm 7.1 support"

# install pytorch with rocm 7.1 support
install-torch-cpu:
    uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --force-reinstall
    @echo "installed torch with CPU support"
