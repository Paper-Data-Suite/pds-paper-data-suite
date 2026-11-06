// Suite #49 Slice 121: independent native Win32 checkpoint-read prototype.
// This is NOT the privileged installer, a service, an approval, or a receipt.
// Never writes, elevates, starts/stops a service, or executes a module.
#include "checkpoint_contract.h"
#include <windows.h>
#include <bcrypt.h>
#include <aclapi.h>
#include <knownfolders.h>
#include <sddl.h>
#include <shlobj.h>

#include <array>
#include <cstdint>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

namespace {
constexpr DWORD kReadShare = FILE_SHARE_READ; // deny simultaneous write/delete
constexpr DWORD kDirectoryFlags = FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT;
constexpr DWORD kRecordFlags = FILE_FLAG_OPEN_REPARSE_POINT;
constexpr DWORD kMutationMask = FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA |
                                FILE_WRITE_ATTRIBUTES | DELETE | FILE_DELETE_CHILD |
                                WRITE_DAC | WRITE_OWNER | GENERIC_WRITE | GENERIC_ALL;
constexpr DWORD kParentDanger = FILE_DELETE_CHILD | DELETE | WRITE_DAC | WRITE_OWNER |
                                GENERIC_WRITE | GENERIC_ALL;
constexpr DWORD kMaxRecord = 4096;
constexpr const char* kNoAuthority =
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY";

class Handle final {
public:
    explicit Handle(HANDLE h = INVALID_HANDLE_VALUE) noexcept : handle_(h) {}
    ~Handle() { if (valid()) { CloseHandle(handle_); } }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& other) noexcept : handle_(std::exchange(other.handle_, INVALID_HANDLE_VALUE)) {}
    Handle& operator=(Handle&& other) noexcept {
        if (this != &other) {
            if (valid()) { CloseHandle(handle_); }
            handle_ = std::exchange(other.handle_, INVALID_HANDLE_VALUE);
        }
        return *this;
    }
    [[nodiscard]] bool valid() const noexcept {
        return handle_ != INVALID_HANDLE_VALUE && handle_ != nullptr;
    }
    [[nodiscard]] HANDLE get() const noexcept { return handle_; }
private:
    HANDLE handle_;
};

struct LocalMemory final {
    explicit LocalMemory(void* p = nullptr) noexcept : ptr(p) {}
    ~LocalMemory() { if (ptr != nullptr) { LocalFree(ptr); } }
    LocalMemory(const LocalMemory&) = delete;
    LocalMemory& operator=(const LocalMemory&) = delete;
    void* ptr;
};

bool privileged_sid(PSID principal) {
    if (principal == nullptr || !IsValidSid(principal)) { return false; }
    constexpr const wchar_t* kPrivileged[] = {
        L"S-1-5-18", // LocalSystem
        L"S-1-5-32-544", // Builtin Administrators
        L"S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    };
    for (const auto* text : kPrivileged) {
        PSID value = nullptr;
        if (!ConvertStringSidToSidW(text, &value)) { return false; }
        const LocalMemory owned(value);
        if (EqualSid(principal, value)) { return true; }
    }
    return false;
}

// Conservative DACL inspection: unknown ACE forms cannot establish custody.
// The ProgramData root allows harmless create rights; protected children do not.
bool audit_acl(HANDLE handle, bool program_data_parent) {
    PSID owner = nullptr;
    PACL dacl = nullptr;
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    const DWORD code = GetSecurityInfo(handle, SE_FILE_OBJECT,
        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
        &owner, nullptr, &dacl, nullptr, &descriptor);
    const LocalMemory owned_descriptor(descriptor);
    if (code != ERROR_SUCCESS || descriptor == nullptr || dacl == nullptr ||
        !privileged_sid(owner)) { return false; }
    ACL_SIZE_INFORMATION size{};
    if (!GetAclInformation(dacl, &size, sizeof(size), AclSizeInformation) ||
        size.AceCount == 0 || size.AceCount > 128) { return false; }
    for (DWORD i = 0; i < size.AceCount; ++i) {
        void* raw = nullptr;
        if (!GetAce(dacl, i, &raw) || raw == nullptr) { return false; }
        const auto* header = static_cast<const ACE_HEADER*>(raw);
        if (header->AceType != ACCESS_ALLOWED_ACE_TYPE &&
            header->AceType != ACCESS_DENIED_ACE_TYPE) { return false; }
        if (header->AceSize < sizeof(ACCESS_ALLOWED_ACE)) { return false; }
        if (header->AceType != ACCESS_ALLOWED_ACE_TYPE ||
            (header->AceFlags & INHERIT_ONLY_ACE) != 0) { continue; }
        const auto* ace = static_cast<const ACCESS_ALLOWED_ACE*>(raw);
        PSID principal = const_cast<DWORD*>(&ace->SidStart);
        if (!IsValidSid(principal)) { return false; }
        const DWORD dangerous = program_data_parent ? kParentDanger : kMutationMask;
        if (!privileged_sid(principal) && (ace->Mask & dangerous) != 0) {
            return false;
        }
    }
    return true;
}

bool open_checked(const std::wstring& path, bool directory, bool parent,
                  Handle& into) {
    const DWORD flags = directory ? kDirectoryFlags : kRecordFlags;
    const DWORD access = READ_CONTROL | FILE_READ_ATTRIBUTES |
                         (directory ? 0 : FILE_READ_DATA);
    Handle candidate(CreateFileW(path.c_str(), access, kReadShare, nullptr,
                                 OPEN_EXISTING, flags, nullptr));
    if (!candidate.valid()) { return false; }
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(candidate.get(), &info)) { return false; }
    if ((info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
        (((info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) != directory) ||
        (!directory && info.nNumberOfLinks != 1)) { return false; }
    if (!audit_acl(candidate.get(), parent)) { return false; }
    into = std::move(candidate);
    return true;
}

bool bounded_read(HANDLE handle, std::vector<std::uint8_t>& output) {
    LARGE_INTEGER length{};
    if (!GetFileSizeEx(handle, &length) || length.QuadPart <= 0 ||
        length.QuadPart > static_cast<LONGLONG>(kMaxRecord)) { return false; }
    std::array<std::uint8_t, kMaxRecord + 1> buffer{};
    DWORD read = 0;
    if (!ReadFile(handle, buffer.data(), static_cast<DWORD>(buffer.size()),
                  &read, nullptr) || read != static_cast<DWORD>(length.QuadPart)) { return false; }
    output.assign(buffer.begin(), buffer.begin() + read);
    return true;
}

bool anchored_program_data(std::wstring& base) {
    PWSTR raw = nullptr;
    if (FAILED(SHGetKnownFolderPath(FOLDERID_ProgramData, KF_FLAG_DEFAULT,
                                    nullptr, &raw)) || raw == nullptr) { return false; }
    const std::wstring copy(raw);
    CoTaskMemFree(raw);
    if (copy.size() < 4 || copy.find(L'\\') == std::wstring::npos ||
        copy.find(L"..") != std::wstring::npos) { return false; }
    base = copy;
    while (!base.empty() && base.back() == L'\\') { base.pop_back(); }
    return !base.empty();
}

bool sha256_checkpoint(const std::vector<std::uint8_t>& data, std::string& hex) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0)
        return false;
    std::array<UCHAR, 32> bytes{};
    const NTSTATUS status = BCryptHash(
        algorithm, nullptr, 0,
        const_cast<PUCHAR>(reinterpret_cast<const UCHAR*>(data.data())),
        static_cast<ULONG>(data.size()), bytes.data(), static_cast<ULONG>(bytes.size()));
    BCryptCloseAlgorithmProvider(algorithm, 0);
    if (status < 0) return false;
    constexpr char kHex[] = "0123456789abcdef";
    hex.clear();
    hex.reserve(64);
    for (const UCHAR byte : bytes) {
        hex.push_back(kHex[byte >> 4]);
        hex.push_back(kHex[byte & 15]);
    }
    return true;
}

bool inspect_records() {
    std::wstring base;
    if (!anchored_program_data(base)) { return false; }
    const std::wstring app = base + L"\\Paper Data Suite";
    const std::wstring state = app + L"\\service-state";
    const std::wstring checkpoint = state + L"\\installer-checkpoint-v1.json";
    const std::wstring journal = state + L"\\installer-intent-journal-v1.json";
    Handle root, app_dir, state_dir, checkpoint_file, journal_file;
    // All five handles remain live until both reads complete.
    if (!open_checked(base, true, true, root) ||
        !open_checked(app, true, false, app_dir) ||
        !open_checked(state, true, false, state_dir) ||
        !open_checked(checkpoint, false, false, checkpoint_file) ||
        !open_checked(journal, false, false, journal_file)) { return false; }
    std::vector<std::uint8_t> checkpoint_bytes;
    std::vector<std::uint8_t> journal_bytes;
    if (!bounded_read(checkpoint_file.get(), checkpoint_bytes) ||
        !bounded_read(journal_file.get(), journal_bytes)) return false;
    std::string observed_digest;
    if (!sha256_checkpoint(checkpoint_bytes, observed_digest)) return false;
    return pds_checkpoint_contract::classify_claims(
        checkpoint_bytes, journal_bytes, observed_digest) !=
        pds_checkpoint_contract::Relationship::invalid;
}

void message(const char* status) {
    std::cout << "{\"status\":\"" << status
              << "\",\"native_read_only\":true,\"protected_write_performed\":false,"
              << "\"administrator_authenticated\":false,\"service_identity_verified\":false,"
              << "\"production_authority\":false,\"active_receipt_authority\":false,"
              << "\"authority\":\"" << kNoAuthority << "\"}\n";
    std::cout << kNoAuthority << '\n';
}
} // namespace

int wmain(int argc, wchar_t* argv[]) {
    // Zero user-configurable paths, keys, payloads and mutation switches.
    // Unknown flags, including --apply and --approve, are denied.
    (void)argv;
    if (argc != 1) { message("REFUSED_UNSUPPORTED_NATIVE_BOOTSTRAP_ARGUMENT"); return 2; }
    const bool observed = inspect_records();
    message(observed ? "NATIVE_WINDOWS_CHECKPOINT_BYTES_OBSERVED_ONLY" :
                      "NATIVE_WINDOWS_CHECKPOINT_CUSTODY_NOT_ESTABLISHED");
    return observed ? 2 : 1;
}
