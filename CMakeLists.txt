cmake_minimum_required(VERSION 3.16)

project(
  swarm_adapter_foundation
  VERSION 0.1.0
  DESCRIPTION "Adapter foundation for multi-robot state streams, map fusion and federated communication policy"
  LANGUAGES CXX
)

include(CTest)
include(GNUInstallDirs)

option(SWARM_ADAPTER_BUILD_DEMO "Build the adapter demo" ON)
option(SWARM_ADAPTER_BUILD_DDS "Build the optional CycloneDDS transport adapter" OFF)

add_library(swarm_adapter
  src/contract/contract_names.cpp
  src/link/adaptive_qos.cpp
  src/link/clock_offset_estimator.cpp
  src/link/keyframe_scheduler.cpp
  src/link/freshness.cpp
  src/fusion/shared_frame_slot.cpp
  src/fusion/submap_registry.cpp
  src/strategy/features.cpp
  src/strategy/safety_envelope.cpp
  src/strategy/policy_model.cpp
  src/strategy/policy_gate.cpp
  src/strategy/ring_strategy_store.cpp
  src/strategy/comm_selector.cpp
  src/directive/directive_gate.cpp
  src/directive/directive_codec.cpp
  src/adapter/file_policy_client.cpp
)
add_library(swarm_adapter::swarm_adapter ALIAS swarm_adapter)

target_compile_features(swarm_adapter PUBLIC cxx_std_17)
set_target_properties(swarm_adapter PROPERTIES CXX_EXTENSIONS OFF)
target_include_directories(swarm_adapter
  PUBLIC
    $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  target_compile_options(swarm_adapter PRIVATE -Wall -Wextra -Wpedantic)
elseif(MSVC)
  target_compile_options(swarm_adapter PRIVATE /W4)
endif()

find_package(Threads REQUIRED)
target_link_libraries(swarm_adapter PUBLIC Threads::Threads)
if(UNIX AND NOT APPLE)
  target_link_libraries(swarm_adapter PUBLIC rt)
endif()

if(SWARM_ADAPTER_BUILD_DEMO)
  add_executable(adapter_demo apps/adapter_demo/main.cpp)
  target_link_libraries(adapter_demo PRIVATE swarm_adapter::swarm_adapter)
endif()

if(UNIX)
  add_executable(swarm_directive_receiver apps/directive_receiver/main.cpp)
  target_link_libraries(swarm_directive_receiver PRIVATE swarm_adapter::swarm_adapter)
endif()

if(BUILD_TESTING)
  foreach(test_name link_tests fusion_tests strategy_tests directive_tests directive_codec_tests)
    add_executable(${test_name} tests/cpp/${test_name}.cpp)
    target_link_libraries(${test_name} PRIVATE swarm_adapter::swarm_adapter)
    add_test(NAME ${test_name} COMMAND ${test_name})
  endforeach()
  target_compile_definitions(strategy_tests PRIVATE
    SWARM_ADAPTER_FIXTURE_DIR="${PROJECT_SOURCE_DIR}/tests/fixtures")
  find_package(Python3 COMPONENTS Interpreter QUIET)
  if(Python3_FOUND AND TARGET swarm_directive_receiver)
    add_test(NAME gateway_directive_e2e
      COMMAND ${CMAKE_COMMAND} -E env
        SWARM_DIRECTIVE_RECEIVER=$<TARGET_FILE:swarm_directive_receiver>
        ${Python3_EXECUTABLE} ${PROJECT_SOURCE_DIR}/gateway/tests/test_task_directive.py)
    set_tests_properties(gateway_directive_e2e PROPERTIES TIMEOUT 60)
  endif()
endif()

if(SWARM_ADAPTER_BUILD_DDS)
  add_subdirectory(adapters/dds)
endif()

install(TARGETS swarm_adapter EXPORT swarm_adapterTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(EXPORT swarm_adapterTargets
  NAMESPACE swarm_adapter::
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/swarm_adapter)
include(CMakePackageConfigHelpers)
file(WRITE ${PROJECT_BINARY_DIR}/swarm_adapterConfig.cmake.in
  "@PACKAGE_INIT@\ninclude(CMakeFindDependencyMacro)\nfind_dependency(Threads)\ninclude(\"\${CMAKE_CURRENT_LIST_DIR}/swarm_adapterTargets.cmake\")\n")
configure_package_config_file(${PROJECT_BINARY_DIR}/swarm_adapterConfig.cmake.in
  ${PROJECT_BINARY_DIR}/swarm_adapterConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/swarm_adapter)
write_basic_package_version_file(${PROJECT_BINARY_DIR}/swarm_adapterConfigVersion.cmake
  COMPATIBILITY SameMajorVersion)
install(FILES
  ${PROJECT_BINARY_DIR}/swarm_adapterConfig.cmake
  ${PROJECT_BINARY_DIR}/swarm_adapterConfigVersion.cmake
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/swarm_adapter)
