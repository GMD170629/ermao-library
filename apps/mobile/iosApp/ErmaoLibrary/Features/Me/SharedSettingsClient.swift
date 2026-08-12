import Foundation
@preconcurrency import ErmaoShared

actor SharedSettingsClient: SettingsClient {
    private let repository: any ErmaoShared.PersonalSettingsRepository
    private let context: ErmaoShared.PersonalSettingsContext

    init(
        repository: any ErmaoShared.PersonalSettingsRepository,
        context: ErmaoShared.PersonalSettingsContext
    ) {
        self.repository = repository
        self.context = context
    }

    func loadSettings() async throws -> (account: SettingsAccount, locale: SettingsLocale) {
        let result = try await repository.loadSettings(context: context)
        let value: ErmaoShared.PersonalSettingsSnapshot = try settingsValue(result)
        return (mapAccount(value.account), mapLocale(value.preferences.locale))
    }

    func updateName(_ name: String) async throws -> SettingsAccount {
        let result = try await repository.updateName(context: context, name: name)
        let value: ErmaoShared.PersonalAccount = try settingsValue(result)
        return mapAccount(value)
    }

    func updateEmail(_ email: String, currentPassword: String) async throws -> SettingsAccount {
        let result = try await repository.updateEmail(
            context: context,
            email: email,
            currentPassword: currentPassword
        )
        let value: ErmaoShared.PersonalAccount = try settingsValue(result)
        return mapAccount(value)
    }

    func updatePassword(
        currentPassword: String,
        newPassword: String
    ) async throws -> SettingsPasswordChange {
        let result = try await repository.updatePassword(
            context: context,
            currentPassword: currentPassword,
            newPassword: newPassword
        )
        let value: ErmaoShared.PersonalPasswordChange = try settingsValue(result)
        return SettingsPasswordChange(requiresLogin: value.requiresLogin)
    }

    func loadAvatar(etag: String?) async throws -> SettingsAvatarContent {
        let result = try await repository.loadAvatar(context: context, etag: etag)
        let value: ErmaoShared.PersonalAvatar = try settingsValue(result)
        return SettingsAvatarContent(
            data: data(from: value.bytes),
            contentType: value.contentType,
            etag: value.etag,
            notModified: value.notModified
        )
    }

    func uploadAvatar(_ upload: SettingsAvatarUpload) async throws -> SettingsAccount {
        let result = try await repository.uploadAvatar(
            context: context,
            upload: ErmaoShared.PersonalAvatarUpload(
                bytes: kotlinBytes(from: upload.data),
                mimeType: mapAvatarMimeType(upload.mimeType)
            )
        )
        let value: ErmaoShared.PersonalAccount = try settingsValue(result)
        return mapAccount(value)
    }

    func deleteAvatar() async throws -> SettingsAccount {
        let result = try await repository.deleteAvatar(context: context)
        let value: ErmaoShared.PersonalAccount = try settingsValue(result)
        return mapAccount(value)
    }

    func updateLocale(_ locale: SettingsLocale) async throws -> SettingsLocale {
        let result = try await repository.updateLocale(
            context: context,
            locale: mapLocale(locale)
        )
        let value: ErmaoShared.PersonalPreferences = try settingsValue(result)
        return mapLocale(value.locale)
    }

    func loadServerVersion() async throws -> String {
        let result = try await repository.loadServerAbout(context: context)
        let value: ErmaoShared.PersonalServerAbout = try settingsValue(result)
        return value.serverVersion
    }

    private func settingsValue<Value>(_ result: any ErmaoShared.PersonalSettingsResult) throws -> Value {
        if let failure = result as? ErmaoShared.PersonalSettingsResultFailure {
            throw mapError(failure.error)
        }
        guard
            let content = result as? ErmaoShared.PersonalSettingsResultContent<AnyObject>,
            let value = content.value as? Value
        else {
            throw SettingsClientError(kind: .protocolViolation, code: "INVALID_RESPONSE")
        }
        return value
    }

    private func mapAccount(_ value: ErmaoShared.PersonalAccount) -> SettingsAccount {
        SettingsAccount(
            id: value.id,
            displayName: value.displayName,
            email: value.email,
            avatarURL: value.avatarUrl
        )
    }

    private func mapLocale(_ value: ErmaoShared.PersonalSettingsLocale) -> SettingsLocale {
        value.wireValue == SettingsLocale.enUS.rawValue ? .enUS : .zhCN
    }

    private func mapLocale(_ value: SettingsLocale) -> ErmaoShared.PersonalSettingsLocale {
        switch value {
        case .zhCN: .zhcn
        case .enUS: .enus
        }
    }

    private func mapAvatarMimeType(
        _ value: SettingsAvatarMimeType
    ) -> ErmaoShared.PersonalAvatarMimeType {
        switch value {
        case .jpeg: .jpeg
        case .png: .png
        case .webP: .webp
        }
    }

    private func mapError(_ value: ErmaoShared.PersonalSettingsError) -> SettingsClientError {
        SettingsClientError(
            kind: mapErrorKind(value.kind.name),
            code: value.code,
            fieldViolations: value.fieldViolations.map {
                SettingsFieldViolation(field: $0.field, code: $0.code)
            }
        )
    }

    private func mapErrorKind(_ name: String) -> SettingsClientErrorKind {
        switch name {
        case "Validation": .validation
        case "Unauthorized": .unauthorized
        case "Forbidden": .forbidden
        case "NotFound": .notFound
        case "Conflict": .conflict
        case "RateLimited": .rateLimited
        case "Server": .server
        case "Transport": .transport
        default: .protocolViolation
        }
    }

    private func data(from bytes: KotlinByteArray) -> Data {
        Data((0..<Int(bytes.size)).map { UInt8(bitPattern: bytes.get(index: Int32($0))) })
    }

    private func kotlinBytes(from data: Data) -> KotlinByteArray {
        let bytes = KotlinByteArray(size: Int32(data.count))
        for (index, value) in data.enumerated() {
            bytes.set(index: Int32(index), value: Int8(bitPattern: value))
        }
        return bytes
    }
}
