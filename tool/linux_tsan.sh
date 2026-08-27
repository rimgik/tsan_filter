#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  linux_tsan.sh configure SOURCE_DIR BUILD_DIR
  linux_tsan.sh build BUILD_DIR
  linux_tsan.sh check BUILD_DIR
  linux_tsan.sh compile-stock BUILD_DIR SOURCE OUTPUT [EXTRA_FLAGS...]
  linux_tsan.sh compile-filter BUILD_DIR SOURCE OUTPUT [EXTRA_FLAGS...]
  linux_tsan.sh run-stock BINARY [ARGS...]
  linux_tsan.sh run-filter BINARY [ARGS...]
  linux_tsan.sh measure-stock BINARY [ARGS...]
  linux_tsan.sh measure-filter BINARY [ARGS...]
  linux_tsan.sh info BUILD_DIR

Environment:
  JOBS                    Parallel build jobs (default: nproc)
  LLVM_TARGETS_TO_BUILD   LLVM target (default derived from uname -m)
  BOOTSTRAP_CC            C compiler used to build LLVM (default: clang)
  BOOTSTRAP_CXX           C++ compiler used to build LLVM (default: clang++)
  TSAN_OPTIONS            Additional runtime options to preserve
EOF
}

need_args() {
  local expected=$1
  local actual=$2
  if (( actual < expected )); then
    usage >&2
    exit 2
  fi
}

native_llvm_target() {
  case "$(uname -m)" in
    aarch64 | arm64) printf '%s\n' AArch64 ;;
    x86_64 | amd64) printf '%s\n' X86 ;;
    *) printf '%s\n' Native ;;
  esac
}

configure() {
  local source_dir=$1
  local build_dir=$2
  local target=${LLVM_TARGETS_TO_BUILD:-$(native_llvm_target)}
  local cc=${BOOTSTRAP_CC:-clang}
  local cxx=${BOOTSTRAP_CXX:-clang++}
  local -a options=(
    -G Ninja
    -DCMAKE_BUILD_TYPE=Release
    -DCMAKE_C_COMPILER="$cc"
    -DCMAKE_CXX_COMPILER="$cxx"
    -DLLVM_ENABLE_ASSERTIONS=OFF
    -DLLVM_ENABLE_PROJECTS=clang
    -DLLVM_ENABLE_RUNTIMES=compiler-rt
    -DLLVM_INCLUDE_TESTS=ON
    -DLLVM_TARGETS_TO_BUILD="$target"
    -DCOMPILER_RT_BUILD_LIBFUZZER=OFF
    -DCOMPILER_RT_BUILD_MEMPROF=OFF
    -DCOMPILER_RT_BUILD_ORC=OFF
    -DCOMPILER_RT_BUILD_XRAY=OFF
  )

  if command -v ccache >/dev/null 2>&1; then
    options+=(-DLLVM_CCACHE_BUILD=ON)
  fi

  cmake -S "$source_dir/llvm" -B "$build_dir" "${options[@]}"
}

build() {
  local build_dir=$1
  local jobs=${JOBS:-$(nproc)}
  cmake --build "$build_dir" --target clang compiler-rt -j "$jobs"
}

check() {
  local build_dir=$1
  local jobs=${JOBS:-$(nproc)}
  local test_build=$build_dir
  if [[ -f $build_dir/runtimes/runtimes-bins/build.ninja ]]; then
    test_build=$build_dir/runtimes/runtimes-bins
  fi
  cmake --build "$test_build" --target check-tsan -j "$jobs"
}

source_compiler() {
  local build_dir=$1
  local source_file=$2
  case "$source_file" in
    *.c) printf '%s\n' "$build_dir/bin/clang" ;;
    *) printf '%s\n' "$build_dir/bin/clang++" ;;
  esac
}

compile() {
  local variant=$1
  local build_dir=$2
  local source_file=$3
  local output=$4
  shift 4

  local compiler
  compiler=$(source_compiler "$build_dir" "$source_file")
  local -a flags=(-O1 -gline-tables-only -fsanitize=thread)
  if [[ $variant == filter ]]; then
    flags+=(-mllvm -tsan-one-word-filter)
  fi

  "$compiler" "${flags[@]}" "$source_file" -o "$output" "$@"
}

filter_options() {
  if [[ -n ${TSAN_OPTIONS:-} ]]; then
    printf '%s\n' "${TSAN_OPTIONS}:one_word_filter=1"
  else
    printf '%s\n' one_word_filter=1
  fi
}

run_filter() {
  local binary=$1
  shift
  local options
  options=$(filter_options)
  env TSAN_OPTIONS="$options" "$binary" "$@"
}

measure() {
  local variant=$1
  local binary=$2
  shift 2
  local -a time_args=(-f 'wall_s=%e user_s=%U sys_s=%S max_rss_kib=%M minor_faults=%R major_faults=%F voluntary_cs=%w involuntary_cs=%c')

  if [[ $variant == filter ]]; then
    local options
    options=$(filter_options)
    /usr/bin/time "${time_args[@]}" env TSAN_OPTIONS="$options" "$binary" "$@"
  else
    /usr/bin/time "${time_args[@]}" "$binary" "$@"
  fi
}

command_name=${1:-}
if [[ -z $command_name ]]; then
  usage >&2
  exit 2
fi
shift

case "$command_name" in
  configure)
    need_args 2 "$#"
    configure "$1" "$2"
    ;;
  build)
    need_args 1 "$#"
    build "$1"
    ;;
  check)
    need_args 1 "$#"
    check "$1"
    ;;
  compile-stock | compile-filter)
    need_args 3 "$#"
    variant=${command_name#compile-}
    compile "$variant" "$@"
    ;;
  run-stock)
    need_args 1 "$#"
    "$@"
    ;;
  run-filter)
    need_args 1 "$#"
    run_filter "$@"
    ;;
  measure-stock | measure-filter)
    need_args 1 "$#"
    variant=${command_name#measure-}
    measure "$variant" "$@"
    ;;
  info)
    need_args 1 "$#"
    "$1/bin/clang" --version
    ;;
  -h | --help | help)
    usage
    ;;
  *)
    printf 'Unknown command: %s\n' "$command_name" >&2
    usage >&2
    exit 2
    ;;
esac
