#pragma once
// Immutable sparse channel matrix. No allocation or locks in process().
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <vector>
#include <utility>

namespace mux {
struct ChannelConnection {
    uint32_t source = 0;
    uint32_t destination = 0;
    double gain = 1.0;
};
struct PcmEncoding {
    uint16_t channels = 0;
    uint16_t bits = 0;
    uint16_t valid_bits = 0;
    bool floating = false;
    bool supported() const {
        return channels > 0 && channels <= 64 &&
            ((floating && bits == 32) || (!floating && (bits == 16 || bits == 24 || bits == 32))) &&
            valid_bits > 0 && valid_bits <= bits;
    }
    double read(const uint8_t* data) const noexcept {
        if (floating) {
            float value; std::memcpy(&value, data, sizeof(value));
            return std::isfinite(value) ? value : 0.0;
        }
        uint32_t word = 0;
        for (unsigned i = 0; i < static_cast<unsigned>(bits) / 8u; ++i) word |= uint32_t(data[i]) << (8 * i);
        // Valid PCM bits are left-aligned in their container (WAVEFORMATEXTENSIBLE).
        const int64_t signedValue = word & (uint32_t(1) << (bits - 1))
            ? int64_t(word) - (int64_t(1) << bits) : int64_t(word);
        return double(signedValue) / double(uint64_t(1) << (bits - 1));
    }
};
class ChannelMatrix {
    PcmEncoding source_;
    uint32_t outputs_;
    std::vector<ChannelConnection> connections_;
public:
    ChannelMatrix(PcmEncoding source, uint32_t outputs, std::vector<ChannelConnection> connections)
        : source_(source), outputs_(outputs), connections_(std::move(connections)) {
        if (!source.supported() || outputs == 0 || outputs > 64 || connections_.empty() || connections_.size() > 1024)
            throw std::invalid_argument("Unsupported channel matrix or source PCM encoding");
        for (size_t i = 0; i < connections_.size(); ++i) {
            const auto& c = connections_[i];
            if (c.source >= source.channels || c.destination >= outputs || !std::isfinite(c.gain) || std::abs(c.gain) > 4)
                throw std::invalid_argument("Channel index or gain out of range");
            for (size_t j = 0; j < i; ++j)
                if (connections_[j].source == c.source && connections_[j].destination == c.destination)
                    throw std::invalid_argument("Duplicate channel connection");
        }
    }
    // Per-destination accumulation in double precision; explicit peak clamp.
    // Unmapped destinations are silent. No implicit downmix/normalization.
    uint64_t process(const uint8_t* input, float* output, size_t frames) const noexcept {
        uint64_t clipped = 0;
        const size_t sampleBytes = source_.bits / 8;
        for (size_t frame = 0; frame < frames; ++frame) {
            double sums[64]{};
            const auto* src = input + frame * source_.channels * sampleBytes;
            for (const auto& c : connections_) sums[c.destination] += source_.read(src + c.source * sampleBytes) * c.gain;
            for (uint32_t channel = 0; channel < outputs_; ++channel) {
                const double value = sums[channel];
                if (value > 1.0 || value < -1.0) ++clipped;
                output[frame * outputs_ + channel] = static_cast<float>(std::clamp(value, -1.0, 1.0));
            }
        }
        return clipped;
    }
};
} // namespace mux
