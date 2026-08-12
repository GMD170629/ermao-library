package com.ermao.library.features.administrativesettings

import androidx.lifecycle.ViewModelProvider

object AdministrativeSettingsFeatureFactory {
    fun viewModelFactory(
        repository: AdministrativeSettingsRepository,
        context: AdministrativeSettingsContext,
        sideEffects: AdministrativeSettingsSideEffects,
    ): ViewModelProvider.Factory = AdministrativeSettingsViewModel.factory(repository, context, sideEffects)
}
