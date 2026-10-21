// Diagnostic interposer for the pinned OpenVINO2025.4 old-string ABI.
// Never compiles a second model or changes a property. Queries the exact
// CompiledModel instance on which SR requests optimal infer-request count.
#include <openvino/runtime/compiled_model.hpp>
#include <dlfcn.h>
#include <unistd.h>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <chrono>

namespace {
std::string quote(const std::string& s) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c == '\n') out << "\\n";
        else if (c == '\r') out << "\\r";
        else if (c == '\t') out << "\\t";
        else if (c < 32) out << '?';
        else out << c;
    }
    out << '"';
    return out.str();
}
std::string env(const char* key) {
    const char* p = std::getenv(key);
    return p ? p : "";
}
}

ov::Any ov::CompiledModel::get_property(const std::string& name) const {
    using Original = ov::Any (*)(const ov::CompiledModel*, const std::string&);
    static auto original = reinterpret_cast<Original>(dlsym(RTLD_NEXT, "_ZNK2ov13CompiledModel12get_propertyERKSs"));
    if (!original) std::abort();
    auto value = original(this, name);
    if (name != "OPTIMAL_NUMBER_OF_INFER_REQUESTS") return value;
    static std::mutex lock;
    std::lock_guard<std::mutex> guard(lock);
    std::ostringstream json;
    auto now = std::chrono::system_clock::now().time_since_epoch();
    json << "{\"pid\":" << getpid() << ",\"epoch_ns\":"
         << std::chrono::duration_cast<std::chrono::nanoseconds>(now).count()
         << ",\"compiled_model_address\":" << quote(std::to_string(reinterpret_cast<uintptr_t>(this)))
         << ",\"trigger\":" << quote(name)
         << ",\"requested_threads\":" << quote(env("OPENVINO_EMBEDDING_TOTAL_THREADS"))
         << ",\"requested_streams\":" << quote(env("OPENVINO_EMBEDDING_NUM_STREAMS"))
         << ",\"mode\":" << quote(env("SR_AMX_MODE")) << ",\"properties\":{";
    bool first = true;
    for (const char* key : {"INFERENCE_NUM_THREADS", "NUM_STREAMS", "PERFORMANCE_HINT",
                           "PERFORMANCE_HINT_NUM_REQUESTS", "OPTIMAL_NUMBER_OF_INFER_REQUESTS",
                           "INFERENCE_PRECISION_HINT", "ENABLE_CPU_PINNING", "EXECUTION_DEVICES"}) {
        if (!first) json << ',';
        first = false;
        json << quote(key) << ':';
        try {
            auto property = original(this, std::string(key));
            std::ostringstream text;
            property.print(text);
            json << "{\"ok\":true,\"value\":" << quote(text.str()) << '}';
        } catch (const std::exception& e) {
            json << "{\"ok\":false,\"error\":" << quote(e.what()) << '}';
        }
    }
    json << "},\"source\":\"same-process-same-CompiledModel-get_property\"}";
    std::ofstream out("/tmp/sr-compiled-properties.jsonl", std::ios::app);
    out << json.str() << '\n';
    out.flush();
    if (!out) std::abort(); // Do not run unobservable diagnostic inference.
    return value; // Exact original result; no configuration changes.
}