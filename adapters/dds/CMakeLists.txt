# 可选 CycloneDDS 传输适配器。核心库 swarm_adapter 不依赖本目录。
enable_language(C)
find_package(CycloneDDS 0.10 REQUIRED)

idlc_generate(TARGET swarm_adapter_dds_idl FILES ${CMAKE_CURRENT_SOURCE_DIR}/idl/swarm_link.idl)

add_library(swarm_adapter_dds src/dds_transport.cpp src/link_probe.cpp)
add_library(swarm_adapter::swarm_adapter_dds ALIAS swarm_adapter_dds)
target_compile_features(swarm_adapter_dds PUBLIC cxx_std_17)
set_target_properties(swarm_adapter_dds PROPERTIES CXX_EXTENSIONS OFF)
target_include_directories(swarm_adapter_dds PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(swarm_adapter_dds
  PUBLIC swarm_adapter::swarm_adapter CycloneDDS::ddsc
  PRIVATE swarm_adapter_dds_idl)
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  target_compile_options(swarm_adapter_dds PRIVATE
    $<$<COMPILE_LANGUAGE:CXX>:-Wall -Wextra -Wpedantic>)
endif()

add_executable(swarm_link_probe apps/swarm_link_probe.cpp)
target_link_libraries(swarm_link_probe PRIVATE swarm_adapter::swarm_adapter_dds)

if(BUILD_TESTING)
  add_executable(dds_tests tests/dds_tests.cpp)
  target_include_directories(dds_tests PRIVATE ${PROJECT_SOURCE_DIR}/tests/cpp)
  target_link_libraries(dds_tests PRIVATE swarm_adapter::swarm_adapter_dds)
  add_test(NAME dds_tests COMMAND dds_tests)
  set_tests_properties(dds_tests PROPERTIES TIMEOUT 60)
endif()
