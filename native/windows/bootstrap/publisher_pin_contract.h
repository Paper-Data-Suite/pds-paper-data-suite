// Suite #49 Slice 126: strict pure claimed publisher pin schema and revision rules.
// Parsing claims does NOT authenticate an installer, publisher, prior policy,
// Windows certificate, administrative principal, or independently held trust root.
#pragma once

#include <cstddef>
#include <cstdint>
#include <utility>
#include <string>
#include <string_view>

namespace pds_publisher_pin_contract {
constexpr std::uint64_t kMaxRevision = 9007199254740991ULL;
constexpr std::size_t kMaxBytes = 512;

struct PublisherPin {
    std::string certificate_sha256;
    std::string spki_sha256;
    std::uint64_t revision = 0;
};

enum class ClaimedTransition {
    invalid,
    identical_claim_only,
    rotation_claim_requires_independent_native_custody,
};

namespace detail {
class CanonicalReader {
public:
    explicit CanonicalReader(std::string_view value) noexcept : input_(value) {}

    [[nodiscard]] bool literal(std::string_view expected) noexcept {
        if (input_.substr(offset_, expected.size()) != expected) return false;
        offset_ += expected.size();
        return true;
    }
    [[nodiscard]] bool field(std::string_view key) noexcept {
        return literal("\"") && literal(key) && literal("\":");
    }
    [[nodiscard]] bool comma() noexcept { return literal(","); }
    [[nodiscard]] bool complete() const noexcept { return offset_ == input_.size(); }
    [[nodiscard]] bool lowercase_sha256(std::string& out) {
        if (!literal("\"") || input_.size() - offset_ < 65) return false;
        const std::size_t begin = offset_;
        bool nonzero = false;
        for (std::size_t i = 0; i < 64; ++i) {
            const char c = input_[offset_ + i];
            if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
            if (c != '0') nonzero = true;
        }
        offset_ += 64;
        if (!literal("\"") || !nonzero) return false;
        out.assign(input_.substr(begin, 64));
        return true;
    }
    [[nodiscard]] bool revision(std::uint64_t& out) noexcept {
        if (offset_ >= input_.size() || input_[offset_] < '0' ||
            input_[offset_] > '9' || input_[offset_] == '0') return false;
        std::uint64_t value = 0;
        while (offset_ < input_.size() && input_[offset_] >= '0' &&
               input_[offset_] <= '9') {
            const auto digit = static_cast<std::uint64_t>(input_[offset_] - '0');
            if (value > (kMaxRevision - digit) / 10) return false;
            value = value * 10 + digit;
            ++offset_;
        }
        out = value;
        return out != 0;
    }
private:
    std::string_view input_;
    std::size_t offset_ = 0;
};
} // namespace detail

[[nodiscard]] inline bool parse_claimed_pin(std::string_view raw, PublisherPin& out) {
    if (raw.empty() || raw.size() > kMaxBytes) return false;
    detail::CanonicalReader reader(raw);
    PublisherPin candidate;
    std::uint64_t schema = 0;
    if (!(reader.literal("{") && reader.field("certificate_sha256") &&
          reader.lowercase_sha256(candidate.certificate_sha256) &&
          reader.comma() && reader.field("revision") &&
          reader.revision(candidate.revision) &&
          reader.comma() && reader.field("schema") &&
          reader.revision(schema) && schema == 1 &&
          reader.comma() && reader.field("spki_sha256") &&
          reader.lowercase_sha256(candidate.spki_sha256) &&
          reader.literal("}") && reader.complete())) return false;
    out = std::move(candidate);
    return true;
}

// Both inputs are untrusted claims; even a matching result grants NO authority.
[[nodiscard]] inline ClaimedTransition review_claimed_transition(
    std::string_view claimed_previous, std::string_view claimed_candidate) {
    PublisherPin old_pin;
    PublisherPin new_pin;
    if (!parse_claimed_pin(claimed_previous, old_pin) ||
        !parse_claimed_pin(claimed_candidate, new_pin) ||
        new_pin.revision < old_pin.revision) return ClaimedTransition::invalid;
    const bool same = new_pin.certificate_sha256 == old_pin.certificate_sha256 &&
                      new_pin.spki_sha256 == old_pin.spki_sha256;
    if (new_pin.revision == old_pin.revision) {
        return same ? ClaimedTransition::identical_claim_only
                    : ClaimedTransition::invalid;
    }
    return ClaimedTransition::rotation_claim_requires_independent_native_custody;
}
} // namespace pds_publisher_pin_contract
