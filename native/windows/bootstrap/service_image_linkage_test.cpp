// Slice 133 portable C++17 native canonical image comparison and refusal tests.
#include "service_image_linkage.h"
#include <iostream>
#include <string>

namespace {
bool check(bool ok, const char* label) {
    if (!ok) std::cerr << "SLICE133_SERVICE_IMAGE_CONTRACT_FAILED: " << label << '\n';
    return ok;
}
} // namespace

int main() {
    using pds_service_image_linkage::claimed_image_linkage;
    const std::wstring root = L"C:\\Program Files";
    const std::wstring image = L"C:\\Program Files\\Paper Data Suite\\pds-service.exe";
    bool good = true;
    const auto accept = [&](const std::wstring& r, const std::wstring& c,
                            const std::wstring& p, const char* label) {
        good = check(claimed_image_linkage(r, c, p), label) && good;
    };
    const auto reject = [&](const std::wstring& r, const std::wstring& c,
                            const std::wstring& p, const char* label) {
        good = check(!claimed_image_linkage(r, c, p), label) && good;
    };
    accept(root, L"\"" + image + L"\"", image, "canonical-quoted");
    accept(root, L"\"c:\\program files\\paper data suite\\PDS-SERVICE.EXE\"",
           image, "ascii-case-fold");
    accept(root, L"\"C:\\Program Files\\Paper Data Suite\\bin\\service.exe\"",
           L"C:\\Program Files\\Paper Data Suite\\bin\\service.exe", "bounded-child");
    reject(root, image, image, "unquoted-space");
    reject(root, L"\"" + image + L"\" --install", image, "argument-injection");
    reject(root, L"\"" + image + L"\" ", image, "trailing-argument-space");
    reject(root, L"\"" + image, image, "unterminated-quote");
    reject(root, L"" + image + L"\"", image, "unexpected-closing-quote");
    reject(root, L"\"" + image + L"\"", image + L".exe", "process-mismatch");
    reject(root, L"\"" + image + L"\"", L"D:\\Program Files\\Paper Data Suite\\pds-service.exe",
           "process-drive-mismatch");
    reject(root, L"\"C:\\Program Files\\Paper Data Suite Evil\\pds-service.exe\"",
           L"C:\\Program Files\\Paper Data Suite Evil\\pds-service.exe", "prefix-confusion");
    reject(root, L"\"C:\\Program Files\\Paper Data Suite\\..\\evil.exe\"",
           L"C:\\Program Files\\Paper Data Suite\\..\\evil.exe", "dotdot");
    reject(root, L"\"C:\\Program Files\\Paper Data Suite\\.\\service.exe\"",
           L"C:\\Program Files\\Paper Data Suite\\.\\service.exe", "dot-segment");
    reject(root, L"\"C:\\Program Files\\Paper Data Suite\\service.exe:ads\"",
           L"C:\\Program Files\\Paper Data Suite\\service.exe:ads", "alternate-stream");
    reject(root, L"\"C:\\Program Files\\Paper Data Suite\\service.dll\"",
           L"C:\\Program Files\\Paper Data Suite\\service.dll", "non-exe");
    reject(root, L"\"C:\\Program Files\\Paper Data Suite\\service.exe\"",
           L"C:\\Program Files\\Paper Data Suite\\service.exe ", "trailing-space");
    reject(root, L"\"C:\\Program Files\\Paper Data Suite\\service.exe\"",
           L"C:\\Program Files\\Paper Data Suite\\\\service.exe", "double-slash");
    reject(root, L"\"%PROGRAMFILES%\\Paper Data Suite\\service.exe\"",
           image, "environment-expansion");
    reject(root, L"\"\\\\server\\share\\service.exe\"",
           L"\\\\server\\share\\service.exe", "network-image");
    reject(root, L"\"\\\\?\\C:\\Program Files\\Paper Data Suite\\service.exe\"",
           L"\\\\?\\C:\\Program Files\\Paper Data Suite\\service.exe", "device-path");
    reject(root, L"\"C:\\Program Files\\Paper Data Suite\\service.exe\"",
           L"C:\\Program Files\\Paper Data Suite\\servic\u00e9.exe", "nonascii-process");
    reject(root, L"\"" + image + L"\"", image + L"\n", "control-character");
    reject(L"C:\\Program Files\\", L"\"" + image + L"\"", image, "root-trailing-separator");
    reject(L"D:\\Program Files", L"\"" + image + L"\"", image, "different-known-folder");
    reject(root, L"\"" + image + L"\"", L"C:\\Program Files\\Paper Data Suite\\service.exe",
           "different-image");
    reject(root, L"\"" + image + L"\"", L"C:\\Program Files\\Paper Data Suite\\service.exe|cmd",
           "metacharacter");
    reject(root, L"\"" + image + L"\"", L"C:\\Program Files\\Paper Data Suite\\service.exe.",
           "trailing-dot");
    reject(root, L"\"" + image + L"\"", L"C:\\Program Files\\Paper Data Suite\\service.exe\\",
           "directory-not-binary");
    reject(root, std::wstring(4200, L'x'), image, "oversize-command");
    if (!good) return 1;
    std::cout << "SLICE133_NATIVE_SERVICE_IMAGE_CONTRACT_TESTS_PASSED\n";
    return 0;
}
