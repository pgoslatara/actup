#! /bin/bash

set -eou

sudo apt update
sudo apt upgrade
sudo apt install build-essentials git

curl -LsSf https://astral.sh/uv/install.sh | sh

git clone https://github.com/pgoslatara/actup
cd actup
$HOME/.local/bin/uv venv
make install
