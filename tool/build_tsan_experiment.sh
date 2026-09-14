#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 WORKLOAD VARIANT COMPILER SUITE_DIR OUTPUT_DIR" >&2
  exit 2
fi

workload=$1
variant=$2
compiler=$(realpath "$3")
compiler_cxx="$(dirname "$compiler")/clang++"
suite=$(realpath "$4")
output=$(realpath -m "$5")

case "$variant" in
  stock) feature_flags=() ;;
  parallel-note) feature_flags=(-mllvm -tsan-one-word-filter) ;;
  shadow-resident) feature_flags=(-mllvm -tsan-shadow-resident-filter) ;;
  *) echo "unknown variant: $variant" >&2; exit 2 ;;
esac

common=(-O2 -g -fno-omit-frame-pointer -fsanitize=thread)
flags="${common[*]} ${feature_flags[*]}"
mkdir -p "$output/$workload-$variant"
build="$output/$workload-$variant"

case "$workload" in
  redis)
    tar -xzf "$suite/nosql/redis/redis-7.0.15.tar.gz" \
      -C "$build" --strip-components=1
    make -C "$build" -j"${BUILD_JOBS:-4}" \
      CC="$compiler" MALLOC=libc CFLAGS="$flags" LDFLAGS="-fsanitize=thread"
    ;;
  memcached)
    tar -xzf "$suite/nosql/memcached/memcached-1.6.29.tar.gz" \
      -C "$build" --strip-components=1
    (
      cd "$build"
      CC="$compiler" CFLAGS="$flags" LDFLAGS="-fsanitize=thread" \
        ./configure --enable-sasl=no
      make -j"${BUILD_JOBS:-4}"
    )
    ;;
  sqlite)
    sqlite_dir="$suite/sql/sqlite"
    [[ -f "$sqlite_dir/build/sqlite3.c" ]] || {
      echo "run sql/sqlite/download_and_compile_sqlite.sh first" >&2
      exit 3
    }
    "$compiler" $flags -DSQLITE_THREADSAFE=1 \
      "$sqlite_dir/threadtest3.c" "$sqlite_dir/build/sqlite3.c" \
      "$sqlite_dir/sqlite-src-3500200/src/test_multiplex.c" \
      -I"$sqlite_dir/build" \
      -I"$sqlite_dir/sqlite-src-3500200/test" \
      -I"$sqlite_dir/sqlite-src-3500200/src" \
      -ldl -lpthread -lm -o "$build/threadtest3"
    ;;
  ffmpeg)
    tar -xzf "$suite/projects/ffmpeg/FFmpeg-n4.3.9.tar.gz" \
      -C "$build" --strip-components=1
    (
      cd "$build"
      ./configure --prefix="$build/install" --cc="$compiler" \
        --cxx="$compiler_cxx" --extra-libs="-lpthread -lm" \
        --extra-cflags="$flags" --extra-cxxflags="$flags" \
        --extra-ldflags="$flags" --disable-doc --enable-gpl \
        --enable-gnutls --enable-libx264 --enable-libx265 --enable-debug=3 \
        --enable-shared --disable-optimizations --disable-stripping
      make -j"${BUILD_JOBS:-4}"
      make install
    )
    ;;
  *)
    echo "build wrapper does not yet support $workload" >&2
    exit 2
    ;;
esac

{
  echo "suite_commit=$(git -C "$suite" rev-parse HEAD)"
  echo "variant=$variant"
  echo "compiler=$compiler"
  echo "flags=$flags"
  "$compiler" --version | sed -n '1,3p'
} > "$build/build-manifest.txt"
