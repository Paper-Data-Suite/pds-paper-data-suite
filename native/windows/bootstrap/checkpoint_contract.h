// Suite #49 Slice 124: strict canonical checkpoint and journal *claims*.
// These pure validation routines do not authenticate custody, callers, or hashes.
// The native read-only diagnostic must independently hash held-handle bytes.
#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace pds_checkpoint_contract {
constexpr std::size_t kMaxBytes = 4096;
constexpr std::uint64_t kMaxRevision = 9007199254740991ULL;

enum class Relationship {
    invalid,
    prepared_previous,
    replacement_journal_unfinalized,
    replacement_claimed_commit_unverified,
};

namespace detail {
struct Checkpoint {
    std::uint64_t generation = 0;
    std::uint64_t trust_revision = 0;
    std::uint64_t registry_revision = 0;
    std::uint64_t lock_revision = 0;
    std::string trust_digest;
    std::string registry_digest;
    std::string lock_digest;
    std::string request_digest;
    std::string transaction;
};

struct Journal {
    bool prepared = false;
    std::string transaction;
    std::string request_digest;
    std::string previous_digest;
    std::string proposed_digest;
};

class Reader {
public:
    explicit Reader(std::string_view input) noexcept : text_(input) {}

    [[nodiscard]] bool literal(std::string_view expected) noexcept {
        if (text_.substr(pos_, expected.size()) != expected) return false;
        pos_ += expected.size();
        return true;
    }
    [[nodiscard]] bool field(std::string_view name) noexcept {
        return literal("\"") && literal(name) && literal("\":");
    }
    [[nodiscard]] bool comma() noexcept { return literal(","); }
    [[nodiscard]] bool finish() const noexcept { return pos_ == text_.size(); }

    [[nodiscard]] bool number(std::uint64_t& output) noexcept {
        if (pos_ >= text_.size()) return false;
        if (text_[pos_] < '0' || text_[pos_] > '9') return false;
        if (text_[pos_] == '0' && pos_ + 1 < text_.size() &&
            text_[pos_ + 1] >= '0' && text_[pos_ + 1] <= '9') return false;
        std::uint64_t result = 0;
        while (pos_ < text_.size() && text_[pos_] >= '0' && text_[pos_] <= '9') {
            const auto digit = static_cast<std::uint64_t>(text_[pos_] - '0');
            if (result > (kMaxRevision - digit) / 10) return false;
            result = result * 10 + digit;
            ++pos_;
        }
        output = result;
        return true;
    }

    [[nodiscard]] bool hex(std::size_t count, std::string& output) {
        if (!literal("\"") || count > text_.size() - pos_) return false;
        for (std::size_t i = 0; i < count; ++i) {
            const char c = text_[pos_ + i];
            if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
        }
        output.assign(text_.substr(pos_, count));
        pos_ += count;
        return literal("\"");
    }

    [[nodiscard]] bool phase(bool& prepared) noexcept {
        if (literal("\"INTENT_PREPARED\"")) { prepared = true; return true; }
        if (literal("\"CHECKPOINT_REPLACED_CLAIMED\"")) {
            prepared = false;
            return true;
        }
        return false;
    }

private:
    std::string_view text_;
    std::size_t pos_ = 0;
};

[[nodiscard]] inline bool zero(std::string_view value) noexcept {
    for (const char c : value) if (c != '0') return false;
    return true;
}

[[nodiscard]] inline bool parse_checkpoint(std::string_view raw, Checkpoint& cp) {
    if (raw.empty() || raw.size() > kMaxBytes) return false;
    Reader r(raw);
    if (!(r.literal("{") && r.field("generation") && r.number(cp.generation) &&
          r.comma() && r.field("last_request_sha256") && r.hex(64, cp.request_digest) &&
          r.comma() && r.field("last_transaction_id") && r.hex(32, cp.transaction) &&
          r.comma() && r.field("lock_revision") && r.number(cp.lock_revision) &&
          r.comma() && r.field("lock_sha256") && r.hex(64, cp.lock_digest) &&
          r.comma() && r.field("registry_revision") && r.number(cp.registry_revision) &&
          r.comma() && r.field("registry_sha256") && r.hex(64, cp.registry_digest) &&
          r.comma() && r.field("schema"))) return false;
    std::uint64_t schema = 0;
    if (!(r.number(schema) && schema == 1 &&
          r.comma() && r.field("trust_policy_revision") && r.number(cp.trust_revision) &&
          r.comma() && r.field("trust_policy_sha256") && r.hex(64, cp.trust_digest) &&
          r.literal("}") && r.finish())) return false;
    if (cp.trust_revision == 0 || zero(cp.trust_digest)) return false;
    if (cp.generation == 0) {
        return cp.lock_revision == 0 && cp.registry_revision == 0 &&
               zero(cp.lock_digest) && zero(cp.registry_digest) &&
               zero(cp.transaction) && zero(cp.request_digest);
    }
    return cp.lock_revision > 0 && cp.registry_revision > 0 &&
           !zero(cp.lock_digest) && !zero(cp.registry_digest) &&
           !zero(cp.transaction) && !zero(cp.request_digest);
}

[[nodiscard]] inline bool parse_journal(std::string_view raw, Journal& j) {
    if (raw.empty() || raw.size() > kMaxBytes) return false;
    Reader r(raw);
    std::uint64_t previous = 2, proposed = 2, schema = 0;
    if (!(r.literal("{") && r.field("phase") && r.phase(j.prepared) &&
          r.comma() && r.field("previous_checkpoint_sha256") && r.hex(64, j.previous_digest) &&
          r.comma() && r.field("previous_generation") && r.number(previous) &&
          r.comma() && r.field("proposed_checkpoint_sha256") && r.hex(64, j.proposed_digest) &&
          r.comma() && r.field("proposed_generation") && r.number(proposed) &&
          r.comma() && r.field("request_sha256") && r.hex(64, j.request_digest) &&
          r.comma() && r.field("schema") && r.number(schema) &&
          r.comma() && r.field("transaction_id") && r.hex(32, j.transaction) &&
          r.literal("}") && r.finish())) return false;
    return schema == 1 && previous == 0 && proposed == 1 &&
           !zero(j.previous_digest) && !zero(j.proposed_digest) &&
           !zero(j.request_digest) && !zero(j.transaction);
}
} // namespace detail

[[nodiscard]] inline Relationship classify_claims(
    const std::vector<std::uint8_t>& checkpoint,
    const std::vector<std::uint8_t>& journal,
    const std::string& observed_checkpoint_sha256) {
    if (checkpoint.empty() || checkpoint.size() > kMaxBytes ||
        journal.empty() || journal.size() > kMaxBytes ||
        observed_checkpoint_sha256.size() != 64) return Relationship::invalid;
    for (char c : observed_checkpoint_sha256) {
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return Relationship::invalid;
    }
    const std::string_view cp_text(reinterpret_cast<const char*>(checkpoint.data()), checkpoint.size());
    const std::string_view jr_text(reinterpret_cast<const char*>(journal.data()), journal.size());
    detail::Checkpoint cp;
    detail::Journal jr;
    if (!detail::parse_checkpoint(cp_text, cp) || !detail::parse_journal(jr_text, jr))
        return Relationship::invalid;
    if (cp.generation == 0 && jr.prepared &&
        observed_checkpoint_sha256 == jr.previous_digest)
        return Relationship::prepared_previous;
    if (cp.generation == 1 &&
        observed_checkpoint_sha256 == jr.proposed_digest &&
        cp.transaction == jr.transaction && cp.request_digest == jr.request_digest)
        return jr.prepared ? Relationship::replacement_journal_unfinalized
                           : Relationship::replacement_claimed_commit_unverified;
    return Relationship::invalid;
}
} // namespace pds_checkpoint_contract
