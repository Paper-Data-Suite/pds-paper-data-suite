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

# Slice 127: independent read-only signer evidence/claimed pin tests.
add_executable(pds_publisher_pin_evidence_test publisher_pin_evidence_test.cpp)
target_compile_features(pds_publisher_pin_evidence_test PRIVATE cxx_std_17)
if(MSVC)
    target_compile_options(pds_publisher_pin_evidence_test PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_publisher_pin_evidence_test PRIVATE -Wall -Wextra -Werror)
endif()

# Slice 128: read-only fixed-path publisher pin claim observation.
# No publisher approval, provisioning, installation, or trust root mutation.
add_executable(pds_windows_publisher_pin_custody_probe publisher_pin_custody_probe.cpp)
target_compile_features(pds_windows_publisher_pin_custody_probe PRIVATE cxx_std_17)
target_compile_definitions(pds_windows_publisher_pin_custody_probe PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(pds_windows_publisher_pin_custody_probe PRIVATE advapi32 shell32 ole32)
if(MSVC)
    target_compile_options(pds_windows_publisher_pin_custody_probe PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_windows_publisher_pin_custody_probe PRIVATE -Wall -Wextra -Werror)
endif()

# Slice 129: observe primary-token elevation/integrity/admin membership only.
# The diagnostic has no permission to provision or authorize an installer.
add_executable(pds_windows_pin_admin_preflight publisher_pin_admin_preflight.cpp)
target_compile_features(pds_windows_pin_admin_preflight PRIVATE cxx_std_17)
target_compile_definitions(pds_windows_pin_admin_preflight PRIVATE
    UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(pds_windows_pin_admin_preflight PRIVATE advapi32)
if(MSVC)
    target_compile_options(pds_windows_pin_admin_preflight PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_windows_pin_admin_preflight PRIVATE -Wall -Wextra -Werror)
endif()

# Slice 130: read-only fixed-name Windows SCM security inventory.
add_executable(pds_windows_service_scm_probe service_scm_security_probe.cpp)
target_compile_features(pds_windows_service_scm_probe PRIVATE cxx_std_17)
target_compile_definitions(pds_windows_service_scm_probe PRIVATE
    UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(pds_windows_service_scm_probe PRIVATE advapi32)
if(MSVC)
    target_compile_options(pds_windows_service_scm_probe PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_windows_service_scm_probe PRIVATE -Wall -Wextra -Werror)
endif()

# Slice 131: read-only current-token SCM effective open-rights observation.
# This executable has no ability to change the fixed provisional service.
add_executable(pds_windows_service_access_probe service_token_access_probe.cpp)
target_compile_features(pds_windows_service_access_probe PRIVATE cxx_std_17)
target_compile_definitions(pds_windows_service_access_probe PRIVATE
    UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(pds_windows_service_access_probe PRIVATE advapi32)
if(MSVC)
    target_compile_options(pds_windows_service_access_probe PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_windows_service_access_probe PRIVATE -Wall -Wextra -Werror)
endif()

# Slice 132: fail-closed ordinary-primary-token and SCM-rights denial witness.
# This is not an independently authenticated teacher account or installer.
add_executable(pds_windows_teacher_denial_probe teacher_service_denial_probe.cpp)
target_compile_features(pds_windows_teacher_denial_probe PRIVATE cxx_std_17)
target_compile_definitions(pds_windows_teacher_denial_probe PRIVATE
    UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(pds_windows_teacher_denial_probe PRIVATE advapi32)
if(MSVC)
    target_compile_options(pds_windows_teacher_denial_probe PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_windows_teacher_denial_probe PRIVATE -Wall -Wextra -Werror)
endif()

# Slice 133: canonical claimed SCM image linkage (pure portable negative tests).
add_executable(pds_service_image_contract_test service_image_linkage_test.cpp)
target_compile_features(pds_service_image_contract_test PRIVATE cxx_std_17)
if(MSVC)
    target_compile_options(pds_service_image_contract_test PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_service_image_contract_test PRIVATE -Wall -Wextra -Werror)
endif()

# Fixed provisional service only: read-only SCM -> running process -> image.
# Path agreement never authenticates installed service custody or a publisher.
add_executable(pds_windows_service_image_probe service_image_linkage_probe.cpp)
target_compile_features(pds_windows_service_image_probe PRIVATE cxx_std_17)
target_compile_definitions(pds_windows_service_image_probe PRIVATE
    UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(pds_windows_service_image_probe PRIVATE advapi32 shell32 ole32)
if(MSVC)
    target_compile_options(pds_windows_service_image_probe PRIVATE /W4 /WX /permissive- /sdl)
else()
    target_compile_options(pds_windows_service_image_probe PRIVATE -Wall -Wextra -Werror)
endif()
