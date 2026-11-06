// Suite #49 Slice 131: fixed-name SCM access observation for CURRENT token.
// Opening a handle with a requested access right does not exercise that right.
// An unsigned caller-owned diagnostic is not ordinary-teacher identity evidence.
// No service configuration, control, installation, registry or ACL mutation.
#include <windows.h>
#include <winsvc.h>

#include <iostream>

namespace {
constexpr const wchar_t* kService = L"PaperDataSuiteService";
constexpr const char* kNoAuthority =
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY";

class ServiceHandle final {
public:
    explicit ServiceHandle(SC_HANDLE handle = nullptr) noexcept : handle_(handle) {}
    ~ServiceHandle() { if (handle_ != nullptr) CloseServiceHandle(handle_); }
    ServiceHandle(const ServiceHandle&) = delete;
    ServiceHandle& operator=(const ServiceHandle&) = delete;
    [[nodiscard]] bool valid() const noexcept { return handle_ != nullptr; }
    [[nodiscard]] SC_HANDLE get() const noexcept { return handle_; }
private:
    SC_HANDLE handle_;
};

struct Observation {
    bool service_present = false;
    bool complete = false;
    bool change_config = false;
    bool delete_service = false;
    bool change_dacl = false;
    bool change_owner = false;
    bool start_service = false;
    bool stop_service = false;
    bool pause_service = false;
    bool user_control = false;
};

enum class Result { absent, observed, refused };

// OpenServiceW asks Windows to evaluate the actual caller token against SCM.
// We close the handle immediately, without making any privileged operation.
// ACCESS_DENIED is an observed denial; any other error refuses observation.
bool right_granted(SC_HANDLE scm, DWORD desired, bool& granted) {
    const ServiceHandle test(OpenServiceW(scm, kService, desired));
    if (test.valid()) { granted = true; return true; }
    if (GetLastError() == ERROR_ACCESS_DENIED) { granted = false; return true; }
    return false;
}

Result inspect(Observation& output) {
    const ServiceHandle scm(OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT));
    if (!scm.valid()) return Result::refused;
    const ServiceHandle presence(OpenServiceW(scm.get(), kService, SERVICE_QUERY_STATUS));
    if (!presence.valid()) {
        return GetLastError() == ERROR_SERVICE_DOES_NOT_EXIST ?
            Result::absent : Result::refused;
    }
    output.service_present = true;
    if (!right_granted(scm.get(), SERVICE_CHANGE_CONFIG, output.change_config) ||
        !right_granted(scm.get(), DELETE, output.delete_service) ||
        !right_granted(scm.get(), WRITE_DAC, output.change_dacl) ||
        !right_granted(scm.get(), WRITE_OWNER, output.change_owner) ||
        !right_granted(scm.get(), SERVICE_START, output.start_service) ||
        !right_granted(scm.get(), SERVICE_STOP, output.stop_service) ||
        !right_granted(scm.get(), SERVICE_PAUSE_CONTINUE, output.pause_service) ||
        !right_granted(scm.get(), SERVICE_USER_DEFINED_CONTROL, output.user_control))
        return Result::refused;
    output.complete = true;
    return Result::observed;
}

void emit(const char* status, const Observation& o) {
    std::cout << "{\"status\":\"" << status
              << "\",\"native_read_only\":true"
              << ",\"service_present\":" << (o.service_present ? "true" : "false")
              << ",\"access_query_complete\":" << (o.complete ? "true" : "false")
              << ",\"change_config_access_granted\":" << (o.change_config ? "true" : "false")
              << ",\"delete_access_granted\":" << (o.delete_service ? "true" : "false")
              << ",\"write_dac_access_granted\":" << (o.change_dacl ? "true" : "false")
              << ",\"write_owner_access_granted\":" << (o.change_owner ? "true" : "false")
              << ",\"start_access_granted\":" << (o.start_service ? "true" : "false")
              << ",\"stop_access_granted\":" << (o.stop_service ? "true" : "false")
              << ",\"pause_access_granted\":" << (o.pause_service ? "true" : "false")
              << ",\"user_control_access_granted\":" << (o.user_control ? "true" : "false")
              << ",\"independent_teacher_token_verified\":false"
              << ",\"service_identity_verified\":false"
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
        emit("REFUSED_UNSUPPORTED_SERVICE_ACCESS_ARGUMENT", observation);
        return 2;
    }
    switch (inspect(observation)) {
    case Result::absent:
        emit("PROVISIONAL_SERVICE_NOT_INSTALLED_NO_AUTHORITY", observation);
        return 1;
    case Result::observed:
        emit("SCM_CURRENT_TOKEN_ACCESS_OBSERVED_UNVERIFIED", observation);
        return 2;
    case Result::refused:
        emit("SCM_CURRENT_TOKEN_ACCESS_QUERY_REFUSED_NO_AUTHORITY", observation);
        return 1;
    }
    emit("SCM_CURRENT_TOKEN_ACCESS_QUERY_REFUSED_NO_AUTHORITY", observation);
    return 1;
}
