cmake_minimum_required(VERSION 3.24)
project(pds_windows_bootstrap_probe LANGUAGES CXX)

# Standalone, read-only Win32 diagnostic. No install, service, receipt or launch.
if(NOT WIN32)
    message(FATAL_ERROR "PDS native bootstrap diagnostic requires Windows SDK")
endif()

add_executable(pds_windows_bootstrap_probe bootstrap_probe.cpp)
target_compile_features(pds_windows_bootstrap_probe PRIVATE cxx_std_17)
target_compile_definitions(pds_windows_bootstrap_probe PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(pds_windows_bootstrap_probe PRIVATE advapi32 shell32 ole32 bcrypt)

if(MSVC)
    target_compile_options(pds_windows_bootstrap_probe PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_windows_bootstrap_probe PRIVATE -Wall -Wextra -Werror)
endif()

# Pure C++17 negative tests exercise the native record parser on actual CPUs.
add_executable(pds_checkpoint_contract_test checkpoint_contract_test.cpp)
target_compile_features(pds_checkpoint_contract_test PRIVATE cxx_std_17)
if(MSVC)
    target_compile_options(pds_checkpoint_contract_test PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_checkpoint_contract_test PRIVATE -Wall -Wextra -Werror)
endif()

# Slice 125: separate read-only Authenticode observation, never an installer.
add_executable(pds_windows_signature_probe signature_probe.cpp)
target_compile_features(pds_windows_signature_probe PRIVATE cxx_std_17)
target_compile_definitions(pds_windows_signature_probe PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(pds_windows_signature_probe PRIVATE wintrust crypt32)
if(MSVC)
    target_compile_options(pds_windows_signature_probe PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_windows_signature_probe PRIVATE -Wall -Wextra -Werror)
endif()

# Slice 126: pure read-only publisher pin schema tests; NOT a trust root.
add_executable(pds_publisher_pin_contract_test publisher_pin_contract_test.cpp)
target_compile_features(pds_publisher_pin_contract_test PRIVATE cxx_std_17)
if(MSVC)
    target_compile_options(pds_publisher_pin_contract_test PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_publisher_pin_contract_test PRIVATE -Wall -Wextra -Werror)
endif()
