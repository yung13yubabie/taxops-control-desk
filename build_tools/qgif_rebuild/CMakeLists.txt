cmake_minimum_required(VERSION 3.22)
project(TaxOpsQGifRecombine LANGUAGES CXX)

# This is a standalone harness, not Qt's internal qt_internal_add_plugin API.
find_package(Qt6 6.10.2 EXACT REQUIRED COMPONENTS Core Gui GuiPrivate)
set(CMAKE_AUTOMOC ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT DEFINED QGIF_SOURCE_DIR)
    message(FATAL_ERROR "Pass -DQGIF_SOURCE_DIR=<prepared source directory>")
endif()
foreach(input main.cpp qgifhandler.cpp qgifhandler_p.h gif.json)
    if(NOT EXISTS "${QGIF_SOURCE_DIR}/${input}")
        message(FATAL_ERROR "Missing qgif input: ${input}")
    endif()
endforeach()
add_library(qgif MODULE
    "${QGIF_SOURCE_DIR}/main.cpp"
    "${QGIF_SOURCE_DIR}/qgifhandler.cpp"
    "${QGIF_SOURCE_DIR}/qgifhandler_p.h"
    "${QGIF_SOURCE_DIR}/gif.json")
target_include_directories(qgif PRIVATE "${QGIF_SOURCE_DIR}")
target_compile_definitions(qgif PRIVATE QT_PLUGIN)
target_link_libraries(qgif PRIVATE Qt6::Gui Qt6::GuiPrivate)
set_target_properties(qgif PROPERTIES
    PREFIX "" OUTPUT_NAME "qgif"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/imageformats"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/imageformats")
