// Suite #49 Slice 128: read-only Win32 fixed-path publisher-pin observation.
// Owner/DACL inspection cannot authenticate the original provisioner or
// establish rollback resistance. NO installation, service or trust authority.
#include "publisher_pin_contract.h"
#include <windows.h>
#include <aclapi.h>
#include <knownfolders.h>
#include <sddl.h>
#include <shlobj.h>

#include <array>
#include <cstdint>
#include <iostream>
#include <string>
#include <string_view>
#include <utility>

namespace {
constexpr DWORD kShare = FILE_SHARE_READ;
constexpr DWORD kDirectoryFlags = FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT;
constexpr DWORD kFileFlags = FILE_FLAG_OPEN_REPARSE_POINT;
constexpr DWORD kMutation = FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA |
                            FILE_WRITE_ATTRIBUTES | DELETE | FILE_DELETE_CHILD |
                            WRITE_DAC | WRITE_OWNER | GENERIC_WRITE | GENERIC_ALL;
constexpr DWORD kParentMutation = FILE_DELETE_CHILD | DELETE | WRITE_DAC |
                                  WRITE_OWNER | GENERIC_WRITE | GENERIC_ALL;
constexpr const char* kNoAuthority =
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY";

class HeldHandle final {
public:
    explicit HeldHandle(HANDLE h = INVALID_HANDLE_VALUE) noexcept : h_(h) {}
    ~HeldHandle() { if (valid()) CloseHandle(h_); }
    HeldHandle(const HeldHandle&) = delete;
    HeldHandle& operator=(const HeldHandle&) = delete;
    HeldHandle(HeldHandle&& other) noexcept :
        h_(std::exchange(other.h_, INVALID_HANDLE_VALUE)) {}
    HeldHandle& operator=(HeldHandle&& other) noexcept {
        if (this != &other) {
            if (valid()) CloseHandle(h_);
            h_ = std::exchange(other.h_, INVALID_HANDLE_VALUE);
        }
        return *this;
    }
    [[nodiscard]] bool valid() const noexcept {
        return h_ != INVALID_HANDLE_VALUE && h_ != nullptr;
    }
    [[nodiscard]] HANDLE get() const noexcept { return h_; }
private:
    HANDLE h_;
};

class AllocatedLocal final {
public:
    explicit AllocatedLocal(void* p) noexcept : p_(p) {}
    ~AllocatedLocal() { if (p_) LocalFree(p_); }
    AllocatedLocal(const AllocatedLocal&) = delete;
    AllocatedLocal& operator=(const AllocatedLocal&) = delete;
private:
    void* p_;
};

bool privileged_sid(PSID sid) {
    if (sid == nullptr || !IsValidSid(sid)) return false;
    constexpr const wchar_t* allowed[] = {
        L"S-1-5-18", L"S-1-5-32-544",
        L"S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    };
    for (const wchar_t* text : allowed) {
        PSID known = nullptr;
        if (!ConvertStringSidToSidW(text, &known)) return false;
        const AllocatedLocal owned(known);
        if (EqualSid(sid, known)) return true;
    }
    return false;
}

bool restricted_acl(HANDLE handle, bool program_data_parent) {
    PSID owner = nullptr;
    PACL dacl = nullptr;
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    const DWORD result = GetSecurityInfo(handle, SE_FILE_OBJECT,
        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
        &owner, nullptr, &dacl, nullptr, &descriptor);
    const AllocatedLocal owned(descriptor);
    if (result != ERROR_SUCCESS || !descriptor || !dacl ||
        !privileged_sid(owner)) return false;
    ACL_SIZE_INFORMATION info{};
    if (!GetAclInformation(dacl, &info, sizeof(info), AclSizeInformation) ||
        info.AceCount == 0 || info.AceCount > 128) return false;
    const DWORD danger = program_data_parent ? kParentMutation : kMutation;
    for (DWORD index = 0; index < info.AceCount; ++index) {
        void* raw = nullptr;
        if (!GetAce(dacl, index, &raw) || !raw) return false;
        const auto* header = static_cast<const ACE_HEADER*>(raw);
        if (header->AceType != ACCESS_ALLOWED_ACE_TYPE &&
            header->AceType != ACCESS_DENIED_ACE_TYPE) return false;
        if (header->AceSize < sizeof(ACCESS_ALLOWED_ACE)) return false;
        if (header->AceType == ACCESS_DENIED_ACE_TYPE ||
            (header->AceFlags & INHERIT_ONLY_ACE)) continue;
        const auto* ace = static_cast<const ACCESS_ALLOWED_ACE*>(raw);
        PSID principal = const_cast<DWORD*>(&ace->SidStart);
        if (!IsValidSid(principal) ||
            (!privileged_sid(principal) && (ace->Mask & danger) != 0))
            return false;
    }
    return true;
}

bool open_fixed(const std::wstring& path, bool directory, bool program_data_parent,
                HeldHandle& output) {
    const DWORD flags = directory ? kDirectoryFlags : kFileFlags;
    const DWORD rights = READ_CONTROL | FILE_READ_ATTRIBUTES |
        (directory ? 0 : FILE_READ_DATA);
    HeldHandle opened(CreateFileW(path.c_str(), rights, kShare, nullptr,
                                  OPEN_EXISTING, flags, nullptr));
    if (!opened.valid()) return false;
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(opened.get(), &info) ||
        (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
        (((info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) != directory) ||
        (!directory && info.nNumberOfLinks != 1) ||
        !restricted_acl(opened.get(), program_data_parent)) return false;
    output = std::move(opened);
    return true;
}

bool fixed_program_data(std::wstring& output) {
    PWSTR raw = nullptr;
    if (FAILED(SHGetKnownFolderPath(FOLDERID_ProgramData, KF_FLAG_DEFAULT,
                                   nullptr, &raw)) || !raw) return false;
    std::wstring found(raw);
    CoTaskMemFree(raw);
    if (found.size() < 4 || found.find(L'\\') == std::wstring::npos ||
        found.find(L"..") != std::wstring::npos) return false;
    while (!found.empty() && found.back() == L'\\') found.pop_back();
    if (found.empty()) return false;
    output = std::move(found);
    return true;
}

bool bounded_policy_read(HANDLE handle, std::string& result) {
    LARGE_INTEGER length{};
    if (!GetFileSizeEx(handle, &length) || length.QuadPart <= 0 ||
        length.QuadPart > static_cast<LONGLONG>(pds_publisher_pin_contract::kMaxBytes))
        return false;
    std::array<char, pds_publisher_pin_contract::kMaxBytes + 1> raw{};
    DWORD count = 0;
    if (!ReadFile(handle, raw.data(), static_cast<DWORD>(raw.size()),
                  &count, nullptr) || count != static_cast<DWORD>(length.QuadPart))
        return false;
    result.assign(raw.data(), count);
    return true;
}

// Even valid, apparently protected policy bytes are an UNAUTHENTICATED CLAIM.
bool observe_claim() {
    std::wstring base;
    if (!fixed_program_data(base)) return false;
    const std::wstring app = base + L"\\Paper Data Suite";
    const std::wstring state = app + L"\\service-state";
    const std::wstring pin = state + L"\\publisher-pin-v1.json";
    HeldHandle root, app_dir, state_dir, policy_file;
    if (!open_fixed(base, true, true, root) ||
        !open_fixed(app, true, false, app_dir) ||
        !open_fixed(state, true, false, state_dir) ||
        !open_fixed(pin, false, false, policy_file)) return false;
    std::string content;
    if (!bounded_policy_read(policy_file.get(), content)) return false;
    pds_publisher_pin_contract::PublisherPin parsed;
    return pds_publisher_pin_contract::parse_claimed_pin(content, parsed);
}

void report(const char* status) {
    std::cout << "{\"status\":\"" << status
              << "\",\"native_read_only\":true,\"publisher_pin_claim_observed\":"
              << (std::string_view(status) == "NATIVE_PIN_CLAIM_OBSERVED_CUSTODY_UNPROVEN" ?
                  "true" : "false")
              << ",\"independent_provisioner_authenticated\":false,"
              << "\"rollback_protection_verified\":false,"
              << "\"publisher_pin_verified\":false,\"authorized_to_install\":false,"
              << "\"authority\":\"" << kNoAuthority << "\"}\n";
    std::cout << kNoAuthority << '\n';
}
} // namespace

int wmain(int argc, wchar_t* argv[]) {
    (void)argv;
    if (argc != 1) {
        report("REFUSED_UNSUPPORTED_PUBLISHER_PIN_ARGUMENT");
        return 2;
    }
    const bool observed = observe_claim();
    report(observed ? "NATIVE_PIN_CLAIM_OBSERVED_CUSTODY_UNPROVEN" :
                      "NATIVE_PIN_CLAIM_NOT_OBSERVED");
    return observed ? 2 : 1;
}
