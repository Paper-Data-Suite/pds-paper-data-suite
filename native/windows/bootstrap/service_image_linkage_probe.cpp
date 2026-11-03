// Suite #49 Slice 133. Read-only SCM-to-running-process image observation.
// This is NOT installed service authentication, executable custody, a signed
// publisher decision, ordinary-teacher acceptance, or installer authorization.
#include "service_image_linkage.h"
#include <windows.h>
#include <winsvc.h>
#include <knownfolders.h>
#include <shlobj.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

namespace {
constexpr const wchar_t* kService = L"PaperDataSuiteService";
constexpr const char* kNoAuthority =
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY";

class ServiceHandle final {
public:
    explicit ServiceHandle(SC_HANDLE h = nullptr) noexcept : h_(h) {}
    ~ServiceHandle() { if (h_ != nullptr) CloseServiceHandle(h_); }
    ServiceHandle(const ServiceHandle&) = delete;
    ServiceHandle& operator=(const ServiceHandle&) = delete;
    [[nodiscard]] bool valid() const noexcept { return h_ != nullptr; }
    [[nodiscard]] SC_HANDLE get() const noexcept { return h_; }
private:
    SC_HANDLE h_;
};
class Handle final {
public:
    explicit Handle(HANDLE h = INVALID_HANDLE_VALUE) noexcept : h_(h) {}
    ~Handle() { if (valid()) CloseHandle(h_); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    [[nodiscard]] bool valid() const noexcept {
        return h_ != INVALID_HANDLE_VALUE && h_ != nullptr;
    }
    [[nodiscard]] HANDLE get() const noexcept { return h_; }
private:
    HANDLE h_;
};
struct OwnedComString final {
    explicit OwnedComString(PWSTR p = nullptr) noexcept : value(p) {}
    ~OwnedComString() { if (value != nullptr) CoTaskMemFree(value); }
    OwnedComString(const OwnedComString&) = delete;
    OwnedComString& operator=(const OwnedComString&) = delete;
    PWSTR value;
};
struct Observation {
    bool service_present = false;
    bool running_process_observed = false;
    bool path_agreement = false;
    bool held_file_observed = false;
};
enum class Result { absent, not_running, observed, refused };

// Defensive bounded extraction from an OS-filled QUERY_SERVICE_CONFIG buffer.
bool read_configured_image(const std::vector<BYTE>& buffer, const wchar_t* pointer,
                           std::wstring& into) {
    if (pointer == nullptr) return false;
    const auto begin = reinterpret_cast<std::uintptr_t>(buffer.data());
    const auto at = reinterpret_cast<std::uintptr_t>(pointer);
    if (at < begin || at >= begin + buffer.size() ||
        (at - begin) % alignof(wchar_t) != 0) return false;
    const std::size_t capacity = (buffer.size() - static_cast<std::size_t>(at - begin)) /
                                 sizeof(wchar_t);
    if (capacity == 0 || capacity > 8192) return false;
    std::size_t length = 0;
    while (length < capacity && pointer[length] != L'\0') ++length;
    if (length == capacity || length == 0 || length > 4098) return false;
    into.assign(pointer, length);
    return true;
}

Result inspect(Observation& found) {
    const ServiceHandle scm(OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT));
    if (!scm.valid()) return Result::refused;
    const ServiceHandle service(OpenServiceW(scm.get(), kService,
                                            SERVICE_QUERY_CONFIG | SERVICE_QUERY_STATUS));
    if (!service.valid()) return GetLastError() == ERROR_SERVICE_DOES_NOT_EXIST ?
        Result::absent : Result::refused;
    found.service_present = true;

    DWORD bytes_needed = 0;
    (void)QueryServiceConfigW(service.get(), nullptr, 0, &bytes_needed);
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER ||
        bytes_needed < sizeof(QUERY_SERVICE_CONFIGW) || bytes_needed > 8192)
        return Result::refused;
    std::vector<BYTE> config_bytes(bytes_needed);
    const auto* config = reinterpret_cast<const QUERY_SERVICE_CONFIGW*>(config_bytes.data());
    if (!QueryServiceConfigW(service.get(),
                             reinterpret_cast<LPQUERY_SERVICE_CONFIGW>(config_bytes.data()),
                             static_cast<DWORD>(config_bytes.size()), &bytes_needed) ||
        bytes_needed > config_bytes.size() ||
        config->dwServiceType != SERVICE_WIN32_OWN_PROCESS)
        return Result::refused;
    std::wstring configured;
    if (!read_configured_image(config_bytes, config->lpBinaryPathName, configured))
        return Result::refused;

    SERVICE_STATUS_PROCESS state{};
    if (!QueryServiceStatusEx(service.get(), SC_STATUS_PROCESS_INFO,
                              reinterpret_cast<LPBYTE>(&state), sizeof(state),
                              &bytes_needed)) return Result::refused;
    if (state.dwCurrentState != SERVICE_RUNNING || state.dwProcessId == 0)
        return Result::not_running;
    if (state.dwServiceType != SERVICE_WIN32_OWN_PROCESS) return Result::refused;
    found.running_process_observed = true;
    const Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE,
                                     state.dwProcessId));
    if (!process.valid()) return Result::refused;
    std::array<wchar_t, 4099> process_path{};
    DWORD path_size = static_cast<DWORD>(process_path.size());
    if (!QueryFullProcessImageNameW(process.get(), 0, process_path.data(), &path_size) ||
        path_size == 0 || path_size >= process_path.size()) return Result::refused;
    const std::wstring observed_process(process_path.data(), path_size);

    PWSTR unowned = nullptr;
    if (FAILED(SHGetKnownFolderPath(FOLDERID_ProgramFiles, KF_FLAG_DEFAULT,
                                    nullptr, &unowned)) || unowned == nullptr)
        return Result::refused;
    const OwnedComString program_files(unowned);
    const std::wstring known_root(program_files.value);
    if (!pds_service_image_linkage::claimed_image_linkage(
            known_root, configured, observed_process)) return Result::refused;
    found.path_agreement = true;

    // Final component held open with no write/delete sharing. Not a full
    // ancestor reparse-point audit or a signed executable identity proof.
    const Handle image(CreateFileW(observed_process.c_str(),
                                   READ_CONTROL | FILE_READ_ATTRIBUTES,
                                   FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                                   FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    if (!image.valid()) return Result::refused;
    BY_HANDLE_FILE_INFORMATION attributes{};
    if (!GetFileInformationByHandle(image.get(), &attributes) ||
        (attributes.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0 ||
        (attributes.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
        attributes.nNumberOfLinks != 1) return Result::refused;

    // Compare the handle-resolved DOS path too; parent junction substitutions
    // and different final images must fail closed. This still is not custody.
    std::array<wchar_t, 4099> final_image{};
    const DWORD final_length = GetFinalPathNameByHandleW(
        image.get(), final_image.data(), static_cast<DWORD>(final_image.size()),
        FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    if (final_length < 5 || final_length >= final_image.size() ||
        std::wstring_view(final_image.data(), 4) != L"\\\\?\\") return Result::refused;
    const std::wstring_view final_dos(final_image.data() + 4, final_length - 4);
    if (!pds_service_image_linkage::claimed_image_linkage(
            known_root, configured, final_dos) ||
        !pds_service_image_linkage::detail::equal_ascii_nocase(
            observed_process, final_dos)) return Result::refused;
    found.held_file_observed = true;
    return Result::observed;
}

void emit(const char* status, const Observation& o) {
    std::cout << "{\"status\":\"" << status
              << "\",\"native_read_only\":true"
              << ",\"service_present\":" << (o.service_present ? "true" : "false")
              << ",\"running_process_observed\":"
              << (o.running_process_observed ? "true" : "false")
              << ",\"scm_process_image_agreement_observed\":"
              << (o.path_agreement ? "true" : "false")
              << ",\"held_image_attributes_observed\":"
              << (o.held_file_observed ? "true" : "false")
              << ",\"installed_service_identity_verified\":false"
              << ",\"executable_custody_verified\":false"
              << ",\"independent_teacher_identity_attested\":false"
              << ",\"publisher_pin_verified\":false"
              << ",\"protected_write_performed\":false"
              << ",\"authorized_to_install\":false"
              << ",\"authority\":\"" << kNoAuthority << "\"}\n";
    std::cout << kNoAuthority << '\n';
}
} // namespace

int wmain(int argc, wchar_t* argv[]) {
    (void)argv;
    Observation observation{};
    if (argc != 1) {
        emit("REFUSED_UNSUPPORTED_SERVICE_IMAGE_ARGUMENT", observation);
        return 2;
    }
    switch (inspect(observation)) {
    case Result::absent:
        emit("PROVISIONAL_SERVICE_NOT_INSTALLED_NO_IMAGE_ACCEPTANCE", observation);
        return 1;
    case Result::not_running:
        emit("SERVICE_NOT_RUNNING_NO_IMAGE_ACCEPTANCE", observation);
        return 1;
    case Result::observed:
        emit("SCM_PROCESS_IMAGE_LINKAGE_OBSERVED_UNVERIFIED", observation);
        return 2;
    case Result::refused:
        emit("SERVICE_IMAGE_QUERY_REFUSED_NO_ACCEPTANCE", observation);
        return 1;
    }
    emit("SERVICE_IMAGE_QUERY_REFUSED_NO_ACCEPTANCE", observation);
    return 1;
}
