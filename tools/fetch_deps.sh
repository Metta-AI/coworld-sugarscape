#!/bin/sh
# Reproduce the dependency tree `nimby sync nimby.lock` produces, using nothing
# but git, so CI can do it without installing nimby.
#
# With no arguments this fetches every package in the lock. With arguments it
# fetches only the named ones — the byte-parity suites need `checksums` alone
# (std/md5 moved out of the standard library in Nim 2.x), and that one is
# public, so that job needs no credentials.
#
# Idempotent: an existing clone is checked out at the pin rather than refetched,
# and a --path line already in nim.cfg is not repeated.
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

wanted=${*:-}

# nimby.lock is "<name> <version> <url> <commit>", one package per line.
while read -r name version url commit; do
  [ -n "${name:-}" ] || continue
  if [ -n "$wanted" ]; then
    case " $wanted " in
      *" $name "*) ;;
      *) continue ;;
    esac
  fi
  if [ ! -d "$name/.git" ]; then
    rm -rf "$name"
    git clone --quiet "$url" "$name"
  fi
  git -C "$name" checkout --quiet "$commit"
  # nimby points at src/ where a package has one and at the repository root
  # otherwise; libcurl is the only one here that does not have src/.
  if [ -d "$name/src" ]; then
    line="--path:\"$name/src\""
  else
    line="--path:\"$name\""
  fi
  if [ ! -f nim.cfg ] || ! grep -qxF "$line" nim.cfg; then
    echo "$line" >> nim.cfg
  fi
done < nimby.lock
