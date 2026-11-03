// Suite #49 Slice 130: fixed-name SCM security inventory. READ-ONLY.
// This diagnostic does NOT authenticate a service, provision a publisher pin,
// verify effective teacher permissions, create services, or install anything.
#include <windows.h>
#include <winsvc.h>

#include <array>
#include <iostream>

namespace {
constexpr const wchar_t* kProvisionalService = L"PaperDataSuiteService";
constexpr const char* kNoAuthority =
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY";

class ServiceHandle final {
public:
    explicit ServiceHandle(SC_HANDLE value = nullptr) noexcept : value_(value) {}
    ~ServiceHandle() { if (value_ != nullptr) CloseServiceHandle(value_); }
    ServiceHandle(const ServiceHandle&) = delete;
    ServiceHandle& operator=(const ServiceHandle&) = delete;
    [[nodiscard]] SC_HANDLE get() const noexcept { return value_; }
    [[nodiscard]] bool valid() const noexcept { return value_ != nullptr; }
private:
    SC_HANDLE value_;
};

struct Observation {
    bool present = false;
    bool dacl_observed = false;
    bool sid_type_observed = false;
    bool mutation_ace_observed = false;
};

enum class Result { absent, observed, refused };

bool inspect_service_dacl(SC_HANDLE service, Observation& observation) {
    DWORD needed = 0;
    constexpr SECURITY_INFORMATION kParts =
        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    // The first query is intentionally a size query and cannot change the DACL.
    if (QueryServiceObjectSecurity(service, kParts, nullptr, 0, &needed) ||
        GetLastError() != ERROR_INSUFFICIENT_BUFFER ||
        needed < SECURITY_DESCRIPTOR_MIN_LENGTH || needed > 8192) return false;
    alignas(alignof(SECURITY_DESCRIPTOR)) std::array<BYTE, 8192> bytes{};
    if (!QueryServiceObjectSecurity(service, kParts, bytes.data(), needed, &needed) ||
        needed > bytes.size()) return false;
    const auto descriptor = reinterpret_cast<PSECURITY_DESCRIPTOR>(bytes.data());
    if (!IsValidSecurityDescriptor(descriptor)) return false;
    PSID owner = nullptr;
    BOOL defaulted = FALSE;
    if (!GetSecurityDescriptorOwner(descriptor, &owner, &defaulted) ||
        owner == nullptr || !IsValidSid(owner)) return false;
    PACL dacl = nullptr;
    BOOL present = FALSE;
    if (!GetSecurityDescriptorDacl(descriptor, &present, &dacl, &defaulted) ||
        !present || dacl == nullptr || !IsValidAcl(dacl)) return false;
    ACL_SIZE_INFORMATION acl{};
    if (!GetAclInformation(dacl, &acl, sizeof(acl), AclSizeInformation) ||
        acl.AceCount == 0 || acl.AceCount > 128) return false;
    constexpr DWORD kSensitive = SERVICE_CHANGE_CONFIG | SERVICE_START |
        SERVICE_STOP | SERVICE_PAUSE_CONTINUE | SERVICE_USER_DEFINED_CONTROL |
        DELETE | WRITE_DAC | WRITE_OWNER | GENERIC_ALL | GENERIC_WRITE |
        GENERIC_EXECUTE;
    bool contains_sensitive_ace = false;
    for (DWORD index = 0; index < acl.AceCount; ++index) {
        void* raw = nullptr;
        if (!GetAce(dacl, index, &raw) || raw == nullptr) return false;
        const auto* header = static_cast<const ACE_HEADER*>(raw);
        if (header->AceType != ACCESS_ALLOWED_ACE_TYPE &&
            header->AceType != ACCESS_DENIED_ACE_TYPE) return false;
        if (header->AceSize < sizeof(ACCESS_ALLOWED_ACE)) return false;
        if (header->AceType == ACCESS_ALLOWED_ACE_TYPE &&
            (header->AceFlags & INHERIT_ONLY_ACE) == 0) {
            const auto* ace = static_cast<const ACCESS_ALLOWED_ACE*>(raw);
            const PSID sid = const_cast<DWORD*>(&ace->SidStart);
            if (!IsValidSid(sid)) return false;
            contains_sensitive_ace |= (ace->Mask & kSensitive) != 0;
        }
    }
    observation.dacl_observed = true;
    observation.mutation_ace_observed = contains_sensitive_ace;
    return true;
}

Result inspect(Observation& observation) {
    const ServiceHandle manager(OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT));
    if (!manager.valid()) return Result::refused;
    const ServiceHandle service(OpenServiceW(
        manager.get(), kProvisionalService, READ_CONTROL | SERVICE_QUERY_CONFIG));
    if (!service.valid()) {
        return GetLastError() == ERROR_SERVICE_DOES_NOT_EXIST ?
            Result::absent : Result::refused;
    }
    observation.present = true;
    if (!inspect_service_dacl(service.get(), observation)) return Result::refused;
    SERVICE_SID_INFO sid{};
    DWORD required = 0;
    if (!QueryServiceConfig2W(service.get(), SERVICE_CONFIG_SERVICE_SID_INFO,
                              reinterpret_cast<LPBYTE>(&sid), sizeof(sid), &required))
        return Result::refused;
    if (sid.dwServiceSidType != SERVICE_SID_TYPE_NONE &&
        sid.dwServiceSidType != SERVICE_SID_TYPE_UNRESTRICTED &&
        sid.dwServiceSidType != SERVICE_SID_TYPE_RESTRICTED)
        return Result::refused;
    observation.sid_type_observed = true;
    return Result::observed;
}

void emit(const char* status, const Observation& value) {
    std::cout << "{\"status\":\"" << status
              << "\",\"native_read_only\":true"
              << ",\"service_present\":" << (value.present ? "true" : "false")
              << ",\"service_dacl_observed\":" << (value.dacl_observed ? "true" : "false")
              << ",\"service_sid_type_observed\":" << (value.sid_type_observed ? "true" : "false")
              << ",\"mutation_ace_observed\":" << (value.mutation_ace_observed ? "true" : "false")
              << ",\"service_identity_verified\":false"
              << ",\"effective_teacher_rights_verified\":false"
              << ",\"publisher_pin_provisioned\":false"
              << ",\"protected_state_write_performed\":false"
              << ",\"authorized_to_provision\":false"
              << ",\"authorized_to_install\":false"
              << ",\"authority\":\"" << kNoAuthority << "\"}\n";
    std::cout << kNoAuthority << '\n';
}
} // namespace

int wmain(int argc, wchar_t* argv[]) {
    (void)argv;
    Observation observation{};
    if (argc != 1) {
        emit("REFUSED_UNSUPPORTED_SCM_ARGUMENT", observation);
        return 2;
    }
    switch (inspect(observation)) {
    case Result::absent:
        emit("PROVISIONAL_SERVICE_NOT_INSTALLED_NO_AUTHORITY", observation);
        return 1;
    case Result::observed:
        emit("SCM_SECURITY_METADATA_OBSERVED_UNVERIFIED", observation);
        return 2;
    case Result::refused:
        emit("SCM_SECURITY_QUERY_REFUSED_NO_AUTHORITY", observation);
        return 1;
    }
    emit("SCM_SECURITY_QUERY_REFUSED_NO_AUTHORITY", observation);
    return 1;
}
