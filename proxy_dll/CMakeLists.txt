cmake_minimum_required(VERSION 3.20)
project(mk_access_proxy LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/minhook)

add_library(dinput8 SHARED
    dllmain.cpp
    log.cpp
    present_hook.cpp
)

target_link_libraries(dinput8 PRIVATE minhook)

set_target_properties(dinput8 PROPERTIES
    OUTPUT_NAME "dinput8"
    PREFIX ""
)
