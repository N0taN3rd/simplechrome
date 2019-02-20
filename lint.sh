#!/usr/bin/env bash

case "$1" in
    "types"*)
     mypy --config-file mypy.ini simplechrome/
    ;;

    "lint"*)
     flake8
    ;;

    *)
     printf "Checking Typing\n"
     mypy --config-file mypy.ini simplechrome/
     printf "\nLinting\n"
     flake8
    ;;
esac
