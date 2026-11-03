// Suite #49 Slice 132: current primary-token SCM denial observation only.
// No token impersonation, account creation, service control, or approval.
// A caller-owned unsigned program cannot attest an independent teacher identity.
#include <windows.h>
#include <winsvc.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <vector>

namespace {
constexpr const wchar_t* kService = L"PaperDataSuiteService";
constexpr const char* kNoAuthority =
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY";

class Handle final {
public:
    explicit Handle(HANDLE value = nullptr) noexcept : value_(value) {}
    ~Handle() { if (value_ != nullptr && value_ != INVALID_HANDLE_VALUE)
        CloseHandle(value_); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    [[nodiscard]] HANDLE get() const noexcept { return value_; }
    [[nodiscard]] bool valid() const noexcept {
        return value_ != nullptr && value_ != INVALID_HANDLE_VALUE;
    }
private:
    HANDLE value_;
};

class ServiceHandle final {
public:
    explicit ServiceHandle(SC_HANDLE value = nullptr) noexcept : value_(value) {}
    ~ServiceHandle() { if (value_ != nullptr) CloseServiceHandle(value_); }
    ServiceHandle(const ServiceHandle&) = delete;
    ServiceHandle& operator=(const ServiceHandle&) = delete;
    [[nodiscard]] bool valid() const noexcept { return value_ != nullptr; }
    [[nodiscard]] SC_HANDLE get() const noexcept { return value_; }
private:
    SC_HANDLE value_;
};

struct Observation {
    bool ordinary_token_observed = false;
    bool service_present = false;
    bool access_complete = false;
    bool all_dangerous_rights_denied = false;
    bool any_dangerous_right_granted = false;
};

enum class TokenResult { ordinary, not_ordinary, refused };
enum class ServiceResult { absent, denied, granted, refused };

// The tested process's primary token only. A UAC-filtered administrator has
// TokenElevationTypeLimited or an Administrators SID in TokenGroups; refuse.
TokenResult inspect_token() {
    HANDLE raw = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &raw))
        return TokenResult::refused;
    const Handle token(raw);
    TOKEN_ELEVATION elevation{};
    TOKEN_ELEVATION_TYPE kind{};
    DWORD size = 0;
    if (!GetTokenInformation(token.get(), TokenElevation, &elevation,
                             sizeof(elevation), &size) ||
        size != sizeof(elevation)) return TokenResult::refused;
    if (!GetTokenInformation(token.get(), TokenElevationType, &kind,
                             sizeof(kind), &size) ||
        size != sizeof(kind)) return TokenResult::refused;
    if (elevation.TokenIsElevated != 0 || kind != TokenElevationTypeDefault)
        return TokenResult::not_ordinary;

    DWORD needed = 0;
    (void)GetTokenInformation(token.get(), TokenIntegrityLevel, nullptr, 0, &needed);
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER ||
        needed < sizeof(TOKEN_MANDATORY_LABEL) || needed > 4096)
        return TokenResult::refused;
    std::vector<BYTE> integrity(needed);
    if (!GetTokenInformation(token.get(), TokenIntegrityLevel, integrity.data(),
                             needed, &size) || size > needed ||
        size < sizeof(TOKEN_MANDATORY_LABEL)) return TokenResult::refused;
    const auto* label = reinterpret_cast<const TOKEN_MANDATORY_LABEL*>(integrity.data());
    if (label->Label.Sid == nullptr || !IsValidSid(label->Label.Sid))
        return TokenResult::refused;
    const PUCHAR subcount = GetSidSubAuthorityCount(label->Label.Sid);
    if (subcount == nullptr || *subcount == 0) return TokenResult::refused;
    const PDWORD rid = GetSidSubAuthority(label->Label.Sid,
                                          static_cast<DWORD>(*subcount - 1));
    if (rid == nullptr) return TokenResult::refused;
    if (*rid < SECURITY_MANDATORY_MEDIUM_RID || *rid >= SECURITY_MANDATORY_HIGH_RID)
        return TokenResult::not_ordinary;

    needed = 0;
    (void)GetTokenInformation(token.get(), TokenGroups, nullptr, 0, &needed);
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER ||
        needed < sizeof(TOKEN_GROUPS) || needed > 65536)
        return TokenResult::refused;
    std::vector<BYTE> group_bytes(needed);
    if (!GetTokenInformation(token.get(), TokenGroups, group_bytes.data(),
                             needed, &size) || size > needed ||
        size < sizeof(TOKEN_GROUPS)) return TokenResult::refused;
    const auto* groups = reinterpret_cast<const TOKEN_GROUPS*>(group_bytes.data());
    if (groups->GroupCount > 1024 ||
        static_cast<std::uint64_t>(groups->GroupCount) * sizeof(SID_AND_ATTRIBUTES) +
            offsetof(TOKEN_GROUPS, Groups) > size) return TokenResult::refused;
    std::array<BYTE, SECURITY_MAX_SID_SIZE> admin{};
    DWORD admin_size = static_cast<DWORD>(admin.size());
    if (!CreateWellKnownSid(WinBuiltinAdministratorsSid, nullptr, admin.data(),
                            &admin_size)) return TokenResult::refused;
    for (DWORD i = 0; i < groups->GroupCount; ++i) {
        PSID sid = groups->Groups[i].Sid;
        if (sid == nullptr || !IsValidSid(sid)) return TokenResult::refused;
        // Includes enabled AND deny-only administrator membership.
        if (EqualSid(sid, admin.data())) return TokenResult::not_ordinary;
    }
    return TokenResult::ordinary;
}

bool check_right(SC_HANDLE scm, DWORD right, bool& granted) {
    const ServiceHandle candidate(OpenServiceW(scm, kService, right));
    if (candidate.valid()) { granted = true; return true; }
    if (GetLastError() == ERROR_ACCESS_DENIED) { granted = false; return true; }
    return false;
}

ServiceResult inspect_service(Observation& observation) {
    const ServiceHandle scm(OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT));
    if (!scm.valid()) return ServiceResult::refused;
    const ServiceHandle present(OpenServiceW(scm.get(), kService, SERVICE_QUERY_STATUS));
    if (!present.valid()) {
        return GetLastError() == ERROR_SERVICE_DOES_NOT_EXIST ?
            ServiceResult::absent : ServiceResult::refused;
    }
    observation.service_present = true;
    constexpr std::array<DWORD, 8> rights{
        SERVICE_CHANGE_CONFIG, DELETE, WRITE_DAC, WRITE_OWNER,
        SERVICE_START, SERVICE_STOP, SERVICE_PAUSE_CONTINUE,
        SERVICE_USER_DEFINED_CONTROL
    };
    bool granted_any = false;
    for (DWORD right : rights) {
        bool granted = false;
        if (!check_right(scm.get(), right, granted)) return ServiceResult::refused;
        granted_any |= granted;
    }
    observation.access_complete = true;
    observation.any_dangerous_right_granted = granted_any;
    observation.all_dangerous_rights_denied = !granted_any;
    return granted_any ? ServiceResult::granted : ServiceResult::denied;
}

void emit(const char* status, const Observation& o) {
    std::cout << "{\"status\":\"" << status
              << "\",\"native_read_only\":true"
              << ",\"ordinary_primary_token_observed\":"
              << (o.ordinary_token_observed ? "true" : "false")
              << ",\"service_present\":" << (o.service_present ? "true" : "false")
              << ",\"access_checks_complete\":" << (o.access_complete ? "true" : "false")
              << ",\"all_eight_dangerous_rights_denied\":"
              << (o.all_dangerous_rights_denied ? "true" : "false")
              << ",\"any_dangerous_right_granted\":"
              << (o.any_dangerous_right_granted ? "true" : "false")
              << ",\"independent_teacher_identity_attested\":false"
              << ",\"installed_service_identity_verified\":false"
              << ",\"publisher_pin_provisioned\":false"
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
        emit("REFUSED_UNSUPPORTED_TEACHER_ACCEPTANCE_ARGUMENT", observation);
        return 2;
    }
    const TokenResult token = inspect_token();
    if (token == TokenResult::refused) {
        emit("ORDINARY_TOKEN_QUERY_REFUSED_NO_ACCEPTANCE", observation);
        return 1;
    }
    if (token != TokenResult::ordinary) {
        emit("CURRENT_TOKEN_NOT_ORDINARY_NO_ACCEPTANCE", observation);
        return 1;
    }
    observation.ordinary_token_observed = true;
    const ServiceResult service = inspect_service(observation);
    switch (service) {
    case ServiceResult::absent:
        emit("SERVICE_NOT_INSTALLED_NO_TEACHER_ACCEPTANCE", observation);
        return 1;
    case ServiceResult::refused:
        emit("SERVICE_RIGHTS_QUERY_REFUSED_NO_ACCEPTANCE", observation);
        return 1;
    case ServiceResult::granted:
        emit("DANGEROUS_SCM_RIGHT_GRANTED_NO_ACCEPTANCE", observation);
        return 1;
    case ServiceResult::denied:
        emit("ALL_EIGHT_SCM_DENIALS_OBSERVED_UNATTESTED", observation);
        return 2;
    }
    emit("SERVICE_RIGHTS_QUERY_REFUSED_NO_ACCEPTANCE", observation);
    return 1;
}
