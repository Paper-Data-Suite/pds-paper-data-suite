// Suite #49 Slice 133: canonical claimed Windows service image linkage.
// A path agreement is NOT authenticated service identity, file custody,
// signer verification, independent ordinary-user acceptance, or authorization.
#pragma once

#include <cstddef>
#include <string>
#include <string_view>

namespace pds_service_image_linkage {
namespace detail {
[[nodiscard]] inline wchar_t lower_ascii(wchar_t c) noexcept {
    return c >= L'A' && c <= L'Z' ? static_cast<wchar_t>(c + (L'a' - L'A')) : c;
}
[[nodiscard]] inline bool equal_ascii_nocase(std::wstring_view a,
                                             std::wstring_view b) noexcept {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i)
        if (lower_ascii(a[i]) != lower_ascii(b[i])) return false;
    return true;
}
[[nodiscard]] inline bool starts_ascii_nocase(std::wstring_view a,
                                              std::wstring_view prefix) noexcept {
    return a.size() >= prefix.size() && equal_ascii_nocase(a.substr(0, prefix.size()), prefix);
}

// Intentionally strict: no UNC, device namespaces, short-name equivalence,
// environment expansion, ADS, dot segments, non-ASCII or ambiguous slashes.
// Rejection of an otherwise legal path is preferable to false trust.
[[nodiscard]] inline bool canonical_drive_path(std::wstring_view value) noexcept {
    if (value.size() < 7 || value.size() > 4096) return false;
    if (!((value[0] >= L'A' && value[0] <= L'Z') ||
          (value[0] >= L'a' && value[0] <= L'z')) ||
        value[1] != L':' || value[2] != L'\\') return false;
    std::size_t begin = 3;
    if (value[3] == L'\\') return false;
    for (std::size_t i = 3; i <= value.size(); ++i) {
        if (i == value.size() || value[i] == L'\\') {
            const auto part = value.substr(begin, i - begin);
            if (part.empty() || part == L"." || part == L".." ||
                part.back() == L'.' || part.back() == L' ') return false;
            begin = i + 1;
        } else {
            const wchar_t c = value[i];
            if (c < 33 || c > 126 || c == L'/' || c == L':' || c == L'"' ||
                c == L'*' || c == L'?' || c == L'<' || c == L'>' ||
                c == L'|' || c == L'%') {
                // Spaces are allowed inside segments but not at the end.
                if (c != L' ') return false;
            }
        }
    }
    return true;
}
[[nodiscard]] inline bool exe_suffix(std::wstring_view value) noexcept {
    return value.size() > 4 &&
           equal_ascii_nocase(value.substr(value.size() - 4), L".exe");
}
} // namespace detail

[[nodiscard]] inline bool claimed_image_linkage(
    std::wstring_view program_files_root, std::wstring_view service_command,
    std::wstring_view observed_process_image) noexcept {
    if (service_command.empty() || service_command.size() > 4098 ||
        !detail::canonical_drive_path(program_files_root) ||
        !detail::canonical_drive_path(observed_process_image)) return false;
    const bool quoted = service_command.front() == L'"';
    if (quoted) {
        if (service_command.size() < 3 || service_command.back() != L'"') return false;
        service_command.remove_prefix(1);
        service_command.remove_suffix(1);
    } else if (service_command.find(L' ') != std::wstring_view::npos) {
        // Windows unquoted service paths with spaces are ambiguous.
        return false;
    }
    if (!detail::canonical_drive_path(service_command) ||
        !detail::exe_suffix(service_command) ||
        !detail::equal_ascii_nocase(service_command, observed_process_image)) return false;
    const std::wstring required_root = std::wstring(program_files_root) +
                                       L"\\Paper Data Suite\\";
    if (!detail::starts_ascii_nocase(observed_process_image, required_root) ||
        observed_process_image.size() <= required_root.size()) return false;
    return true;
}
} // namespace pds_service_image_linkage
