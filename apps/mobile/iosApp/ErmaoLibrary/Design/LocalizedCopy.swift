import Foundation

func localizedAppString(_ key: String, bundle: Bundle = .main, locale: Locale? = nil) -> String {
    let localizationBundle: Bundle
    if let locale {
        let localization: String?
        switch locale.language.languageCode?.identifier {
        case "zh": localization = "zh-Hans"
        case "en": localization = "en"
        default: localization = nil
        }
        if let localization,
           let path = bundle.path(forResource: localization, ofType: "lproj"),
           let selectedBundle = Bundle(path: path) {
            localizationBundle = selectedBundle
        } else {
            localizationBundle = bundle
        }
    } else {
        localizationBundle = bundle
    }
    return localizationBundle.localizedString(forKey: key, value: key, table: nil)
}
