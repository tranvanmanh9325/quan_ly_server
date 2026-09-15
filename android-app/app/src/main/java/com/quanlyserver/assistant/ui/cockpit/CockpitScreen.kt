package com.quanlyserver.assistant.ui.cockpit

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color

/**
 * Main Assistant Cockpit Screen:
 * Powered by True 3D Real-Time Engine (Google model-viewer 3D).
 * Renders the 3D anime female character (.glb) inside the space cockpit,
 * allowing full 360-degree rotation, auto-rotation, and interactive touch controls.
 */
@Composable
fun CockpitScreen() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        // [Core 3D Engine Surface - True GLB 3D Model with 360 Rotation]
        Cockpit3DView(modifier = Modifier.fillMaxSize())
    }
}
