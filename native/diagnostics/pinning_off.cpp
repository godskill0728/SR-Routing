// New experimental control, NOT a read-only diagnostic. Applied equally to
// unbound and bound. Original image and archived libraries remain unchanged.
#include <openvino/runtime/core.hpp>
#include <openvino/runtime/properties.hpp>
#include <dlfcn.h>
#include <unistd.h>
#include <cstdlib>
#include <fstream>
#include <sstream>

ov::CompiledModel ov::Core::compile_model(const std::shared_ptr<const ov::Model>& model,
                                         const std::string& device,
                                         const ov::AnyMap& properties) {
    using Fn = ov::CompiledModel (*)(ov::Core*, const std::shared_ptr<const ov::Model>&,
                                    const std::string&, const ov::AnyMap&);
    static auto original = reinterpret_cast<Fn>(dlsym(RTLD_NEXT,
        "_ZN2ov4Core13compile_modelERKSt10shared_ptrIKNS_5ModelEERKSsRKSt3mapISsNS_3AnyESt4lessISsESaISt4pairIS7_SA_EEE"));
    const char* enabled = std::getenv("SR_EXPERIMENT_PINNING_OFF");
    if (!original || !enabled || std::string(enabled) != "1" || device != "CPU") std::abort();
    // Fail on a preexisting explicit setting rather than silently overriding it.
    if (properties.count(ov::hint::enable_cpu_pinning.name())) std::abort();
    auto controlled = properties;
    controlled[ov::hint::enable_cpu_pinning.name()] = false;
    auto compiled = original(this, model, device, controlled);
    const bool actual = compiled.get_property(ov::hint::enable_cpu_pinning);
    if (actual) std::abort();
    std::ofstream out("/tmp/sr-pinning-control.jsonl", std::ios::app);
    out << "{\"pid\":" << getpid()
        << ",\"device\":\"CPU\",\"added_property\":\"ENABLE_CPU_PINNING\","
           "\"requested\":false,\"actual\":false,\"original_config_size\":" << properties.size()
        << ",\"controlled_config_size\":" << controlled.size()
        << ",\"other_properties_changed\":false}\n";
    out.flush();
    if (!out) std::abort();
    return compiled;
}