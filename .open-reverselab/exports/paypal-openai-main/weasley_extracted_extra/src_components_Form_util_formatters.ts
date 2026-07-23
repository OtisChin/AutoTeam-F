// Internal modules
import { appStore } from '@/store';
import {
  containsRightOfWithdrawalCheckbox,
  features,
  getLocale,
  getToken,
  isSepaMandateCountry,
} from '@/lib';
import type { FormState } from '@/store/models/form/types';
import type { GenericObjectType } from '@/types';
import { UI_STATE_FIELDS_TO_FORM_STATE_MAP } from '../constants';
import {
  getBankPayload,
  getCardPayload,
  getCrsPayload,
  getSignupData,
  getStretchRewardData,
} from './payloadUtils';
import { getDialingCode } from './formOperations';
import {
  getIsSignupIncentiveOptIn,
  getLegalAgreementsData,
  getPomaFlowData,
  stringToDateObject,
} from './miscUtils';
import {
  getBankState,
  getCardState,
  getCommonFormState,
  getForcedValidCopy,
  getInstallmentTermState,
} from './formOperations';
import {
  filterOutNonApplicableAddressFields,
  getAccountQualityMetaDataFromAddress,
  getAddressMetaKey,
  getShippingAddressFromBillingAddress,
  serializeAddressFields,
} from './addressOperations';
import { validateForm } from './validations';
import { getCrsState } from './crsUtils';
import {
  type CollectedConsent,
  CollectedConsentName,
  CollectedConsentType,
  CountryCodes,
  type Installments,
} from '@/generated/graphql';
import type { CardPayload } from './types';
import {
  MARKETING_OPT_IN,
  SIGNUP_AGREE_TO_PRIVACY_STATEMENTS,
  SIGNUP_AGREE_TO_TERMS,
  THIRD_PARTY_DATA_CONSENT,
  UNIQUE_INFORMATION_PROCESSING,
} from '@/lib/features/constants';

/**
 * @function serializeFormDataForGuestUpgradeEligible
 * @param {object} data Form fields that have been filtered based on the flow
 * @returns {object} Returns the formatted graphql variables payload,
 *  including additions such as token, and formatted card, phone inputs
 */
// TODO: Link typing to GQL variables payload
const serializeFormDataForGuestUpgradeEligible = (
  data: FormState,
): GenericObjectType => {
  const {
    email: { value: email },
    firstName: { value: firstName },
    lastName: { value: lastName },
  } = data;
  const { billingAddress } = serializeAddressFields(data);

  return {
    // leaving getBankPayload functional call commented here for the context.
    // why bank payload is not required?
    // Bank payload is not required now, since germany is an SCA country
    // and SCA feature is not implemented for wps upgrade flows.
    // ...getBankPayload(data),
    ...getCardPayload(data),
    billingAddress,
    country: getLocale().country,
    email: email.trim(),
    firstName: firstName.trim(),
    lastName: lastName.trim(),
  };
};

/**
 * @function formatInstallmentOption
 * @param {object} data raw installment data fetched from the server
 * @returns {object} Returns the formmated installment option in
 *  InstallmentsInput type
 */
const formatInstallmentOption = (data: Installments): GenericObjectType => {
  const { discount, monthlyPayment, term, totalCost, feeReferenceId } = data;
  // discount fields do not always exist, default to 0
  // other fields should always exist
  const discountValue = discount?.amount?.currencyValue || '0';
  const discountPercentage = discount?.percentage || '0';
  const { currencyCode: paymentCurrency, currencyValue: paymentValue } =
    monthlyPayment;
  const { currencyCode: totalCostCurrency, currencyValue: totalCostValue } =
    totalCost;

  return {
    selectedInstallmentOption: {
      discountCurrency: paymentCurrency,
      discountPercentage: discountPercentage,
      discountValue: discountValue,
      feeReferenceId,
      paymentCurrency,
      paymentValue,
      term,
      totalCostCurrency,
      totalCostValue,
    },
  };
};

/**
 * @function getCollectedConsents
 * @param {object} data Form fields that have been filtered based on the flow
 * @returns {array} An array containing consents collected from the user during a sign up flow
 */
const getCollectedConsents = (
  data: FormState,
): CollectedConsent[] | undefined => {
  const collectedConsents: CollectedConsent[] = [];

  /**
   * Temporarily feature flagging this change to the signUpNewMember mutation until
   * OAS is ready to consume "Collected consent" data. This is done so that we can enable
   * "collected consents" using ELMO once OAS is ready without waiting on a series of dependent
   * releases.
   *
   * TODO: Remove reliance on this feature flag and make it the default behavior
   * for signUpNewMember mutation after ramping to 100%.
   */
  if (!features.isActive('hasThirdPartyDataConsentCheckbox')) {
    return undefined;
  }

  // User accepted the "Privacy statement" checkbox
  // src/components/SignupFields/LegalDisclosures/PrivacyStatement
  if (data[SIGNUP_AGREE_TO_PRIVACY_STATEMENTS]?.value) {
    collectedConsents.push({
      consentName: CollectedConsentName.PrivacyStatementAgreement,
      consentType: CollectedConsentType.FullConsent,
    });
  }

  // User accepted the "Third party data sharing" checkbox
  // src/components/SignupFields/LegalDisclosures/ThirdPartyDataConsent
  if (data[THIRD_PARTY_DATA_CONSENT]?.value) {
    collectedConsents.push({
      consentName:
        CollectedConsentName.PrivacyStatementThirdPartyDataSharingAgreement,
      consentType: CollectedConsentType.FullConsent,
    });
  }

  // User accepted the "Unique information processing" checkbox
  // src/components/SignupFields/LegalDisclosures/UniqueInformationProcessing
  if (data[UNIQUE_INFORMATION_PROCESSING]?.value) {
    collectedConsents.push({
      consentName:
        CollectedConsentName.PrivacyStatementUniqueIdentificationInformationProcessingAgreement,
      consentType: CollectedConsentType.FullConsent,
    });
  }

  return collectedConsents;
};

/**
 * @function serializeFormData
 * @param {object} data Form fields that have been filtered based on the flow
 * @returns {object} Returns the formatted graphql variables payload,
 *  including additions such as token, and formatted card, phone inputs
 */
// TODO: Improve typing on this function
const serializeFormData = (data: FormState): GenericObjectType => {
  const { ui: uiState, form: formState } = appStore.getState();
  const {
    api: { installmentData },
  } = appStore.getState();
  const { value: onboardOption } = data.onboardOption;
  const isPayLater = uiState.fiType === 'bnpl';
  const isSignup = onboardOption === 'signup';
  const isPOMAEligible = features.isActive('isPOMAEligible');
  const isPasswordlessForcedSignup = features.isActive(
    'passwordlessForcedSignup',
  );
  const isStreamlinePasswordlessForcedSignup =
    features.isActive('isStreamlineForcedExperience') &&
    isPasswordlessForcedSignup;

  const isPasswordlessOptionalSignup = features.isActive(
    'passwordlessOptionalSignup',
  );
  const isStreamlinePasswordlessOptionalSignup =
    features.isActive('isStreamlineOptionalExperience') &&
    isPasswordlessOptionalSignup;

  const isPOMAFlow =
    (isPOMAEligible || isPasswordlessForcedSignup) &&
    isSignup &&
    !isPayLater &&
    !isStreamlinePasswordlessForcedSignup &&
    !isStreamlinePasswordlessOptionalSignup;

  const dialingCode = getDialingCode(data);

  const {
    email: { value: email },
    firstName: { value: firstName },
    lastName: { value: lastName },
    phone: { value: number },
    phoneType: { value: phoneType },
  } = data;

  const installment = installmentData.find(
    ({ term }) => term === Number(data?.installmentTerm?.value),
  ) as Installments;

  const {
    shareAddressWithDonatee: { value: shareAddressWithDonatee },
  } = formState;

  return {
    ...getBankPayload(data),
    ...getCardPayload(data),
    country: getLocale().country,
    ...(uiState.cardFieldsToDisplay.dob && {
      dateOfBirth: stringToDateObject(data.dateOfBirth?.value || ''),
    }),
    email: email.trim(),
    firstName: firstName.trim(),
    lastName: lastName.trim(),
    phone: {
      countryCode: `${dialingCode}`,
      number,
      type: phoneType,
    },
    ...(installment && formatInstallmentOption(installment)),
    ...(features.isActive('isDonation') && {
      shareAddressWithDonatee:
        shareAddressWithDonatee && features.isActive('isDonation'),
    }),
    ...(getStretchRewardData() && {
      isSignupIncentiveOptInStretch: true,
    }),
    supportedThreeDsExperiences: [features.get('threeDsV1Experience')],
    token: getToken(),
    ...serializeAddressFields(data),
    ...(!isPOMAFlow && isSignup && getSignupData(data)),
    ...(isPOMAFlow && getPomaFlowData()),
    ...getCrsPayload(data),
    ...(isSignup && getLegalAgreementsData()),
    ...getIsSignupIncentiveOptIn(data),
    collectedConsents: getCollectedConsents(data),
    ...(features.isActive('shouldDisplayJpKanaAndKanjiNames') &&
      data?.nationality?.value === CountryCodes.Jp && {
        countrySpecificFirstName: data.countrySpecificFirstName?.value,
        countrySpecificLastName: data.countrySpecificLastName?.value,
      }),
    ...(isSignup &&
      features.isActive('shouldDisplayAustraliaMiddleName') && {
        middleName: data.middleName?.value?.trim(),
      }),
  };
};

/**
 * @function serializeOnboardingPlanData
 * @param {object} state
 * @returns {object} returns the formatted graphql payload.
 */
// TODO: Create explicit type for GQL Payload
const serializeOnboardingPlanData = (data: FormState): GenericObjectType => {
  const { api: apiState } = appStore.getState();
  const { cupOtpfundingInstrumentId, cupOtpEncryptedCardLoginAccountNumber } =
    apiState;
  const {
    card: { securityCode: cardCvv },
    currencyConversionType,
  } = getCardPayload(data) as CardPayload;
  const { shippingAddress } = serializeAddressFields(data);
  const token = getToken();
  const { onboardOption } = data;
  // @ts-expect-error Type FilteredFormState
  const isGuest = onboardOption === 'guest';
  const userType = isGuest ? 'GUEST' : 'SIGN_UP';

  return {
    ...(cupOtpEncryptedCardLoginAccountNumber && {
      encryptedCardLoginAccountNumber: cupOtpEncryptedCardLoginAccountNumber,
    }),
    ...(currencyConversionType && { currencyConversionType }),
    cvv: cardCvv,
    fundingInstrumentId: cupOtpfundingInstrumentId,
    shippingAddress,
    supportedThreeDsExperiences: [features.get('threeDsV1Experience')],
    token,
    userType,
  };
};

/**
 * @function filterFormState
 * @param {object} formState
 * @returns {object}
 * @description filters address fields out of the form state that
 *  shouldn't be validated or submitted because they don't apply to
 *  either the flow (isAddressless, !isAllowChangeShipping) or the country
 *  (e.g. no postal code for HK)
 */
// TODO: Create a type for filtered form state
const filterFormState = (formState: FormState): GenericObjectType => {
  const {
    billingAddress,
    firstName,
    lastName,
    residentialAddress,
    shippingAddress,
    phone,
  } = formState;
  const { ui: uiState } = appStore.getState();
  const filteredFormState: GenericObjectType = {
    ...getCommonFormState(formState),
    ...getBankState(formState),
    ...getCardState(formState),
    ...getInstallmentTermState(formState),
    billingAddress: {
      ...filterOutNonApplicableAddressFields(
        billingAddress,
        getAddressMetaKey(),
      ),
      accountQuality: {
        ...getAccountQualityMetaDataFromAddress(billingAddress).accountQuality,
        // SCA phone confimration otp code
        twoFactorPhoneVerificationId: phone.meta?.verificationId,
      },
    },
    shippingAddress: {
      country: shippingAddress.country,
      firstName: shippingAddress.firstName,
      lastName: shippingAddress.lastName,
      ...filterOutNonApplicableAddressFields(
        shippingAddress,
        getAddressMetaKey(shippingAddress.country.value),
      ),
      ...getAccountQualityMetaDataFromAddress(shippingAddress),
    },
    ...(residentialAddress
      ? {
          residentialAddress: {
            ...filterOutNonApplicableAddressFields(
              residentialAddress,
              getAddressMetaKey(),
            ),
          },
        }
      : {}),
    ...getCrsState(formState),
    // DTOPPOR-852: Adding for delayed signup incentives
    ...getIsSignupIncentiveOptIn(formState),
  };

  const { fiType } = uiState;
  // Do not update cardFieldsToDisplay for bank fiType.
  if (fiType === 'card') {
    // Add or remove the fields into filteredFormState based on
    // fields displayed with card - uiState.cardFieldsToDisplay
    const keys = Object.keys(
      uiState.cardFieldsToDisplay,
    ) as (keyof typeof UI_STATE_FIELDS_TO_FORM_STATE_MAP)[];
    keys.forEach(key => {
      const formStateField = UI_STATE_FIELDS_TO_FORM_STATE_MAP[key];
      if (!uiState.cardFieldsToDisplay[key] && formStateField) {
        if (filteredFormState[formStateField]) {
          delete filteredFormState[formStateField];
        }
      } else if (uiState.cardFieldsToDisplay[key] && formStateField) {
        // DOB is displayed with card fields even for guest when card type
        // is Carte Aurore, Cofinoga ou privilege, 4 etoiles
        filteredFormState[formStateField] = formState[formStateField];
      }
    });
  }
  const isOptionalSignup = features.isActive('isOptionalSignup');
  const isPasswordlessOptionalSignup = features.isActive(
    'passwordlessOptionalSignup',
  );
  const isPOMAEligible = features.isActive('isPOMAEligible');
  const isPasswordlessForcedSignup = features.isActive(
    'passwordlessForcedSignup',
  );
  const isStreamlinePasswordlessForcedSignup =
    features.isActive('isStreamlineForcedExperience') &&
    isPasswordlessForcedSignup;

  const isStreamlinePasswordlessOptionalSignup =
    features.isActive('isStreamlineOptionalExperience') &&
    isPasswordlessOptionalSignup;

  // Feature that gets Elmo treatment to render Primary residential address
  const isPrimaryResidentialAddressRequested = features.isActive(
    'hasPrimaryResidentialAddress',
  );

  const onboardOption = formState.onboardOption.value;
  const isSignup = onboardOption === 'signup';
  const isPayLater = fiType === 'bnpl';
  const isPOMAFlow =
    (isPOMAEligible || isPasswordlessForcedSignup) &&
    isSignup &&
    !isPayLater &&
    !isStreamlinePasswordlessForcedSignup &&
    !isStreamlinePasswordlessOptionalSignup;
  if (isOptionalSignup && onboardOption === 'guest') {
    // if optional signup and onboard option selected is guest
    filteredFormState.guestAgreeToTerms = formState.guestAgreeToTerms;
  } else if (isSignup && !isPOMAFlow) {
    // forced sign up or onboard option is signup, but not POMA
    if (
      !isStreamlinePasswordlessForcedSignup &&
      !isStreamlinePasswordlessOptionalSignup
    ) {
      // don't set password for streamline passwordless flow
      filteredFormState.password = formState.password;
    }
    filteredFormState[SIGNUP_AGREE_TO_TERMS] = formState[SIGNUP_AGREE_TO_TERMS];
    filteredFormState[MARKETING_OPT_IN] = formState[MARKETING_OPT_IN];

    if (features.isActive('hasPrivacyStatementTerms')) {
      filteredFormState[SIGNUP_AGREE_TO_PRIVACY_STATEMENTS] =
        formState[SIGNUP_AGREE_TO_PRIVACY_STATEMENTS];
    }

    if (features.isActive('hasUniqueInformationProcessingCheckbox')) {
      filteredFormState[UNIQUE_INFORMATION_PROCESSING] =
        formState[UNIQUE_INFORMATION_PROCESSING];
    }

    if (features.isActive('hasThirdPartyDataConsentCheckbox')) {
      filteredFormState[THIRD_PARTY_DATA_CONSENT] =
        formState[THIRD_PARTY_DATA_CONSENT];
    }

    // adding the kyc fields
    const kycFields = features.config.kycFields;
    kycFields.forEach((field: string) => {
      // We only add secondaryIdentityDocument if
      // countryOfResidence is Russia
      if (
        (field === 'SecondaryIdentityDocumentNumber' ||
          field === 'SecondaryIdentityDocumentType') &&
        formState.countryOfResidence?.value !== 'RU'
      ) {
        return;
      }
      const formattedField = (field[0].toLowerCase() +
        field.substring(1)) as keyof FormState;
      filteredFormState[formattedField] = formState[formattedField];
    });

    if (
      features.isActive('shouldDisplayJpKanaAndKanjiNames') &&
      formState?.nationality?.value === CountryCodes.Jp
    ) {
      filteredFormState.countrySpecificFirstName =
        formState.countrySpecificFirstName;
      filteredFormState.countrySpecificLastName =
        formState.countrySpecificLastName;
    }
    if (features.isActive('shouldDisplayAustraliaMiddleName')) {
      filteredFormState.middleName = formState.middleName;
    }
  }

  // Pay later always creates a new account, so residentialAddress should be included
  // in the payload when hasPrimaryResidentialAddress is active — same as signup.
  // onboardOption.value is not 'signup' in BNPL sessions, so isPayLater is used
  // as an equivalent gate alongside isSignup.
  if (!isPrimaryResidentialAddressRequested || (!isSignup && !isPayLater)) {
    delete filteredFormState.residentialAddress;
  }

  /**
   * FEATURE_SIGNUP_RIGHT_OF_WITHDRAW controls the Right of Withdrawal.
   * If in TREATMENT_2 we show the checkbox.
   * It's just for signups.
   */
  if (containsRightOfWithdrawalCheckbox(onboardOption)) {
    filteredFormState.rightOfWithdrawal = formState.rightOfWithdrawal;
  }

  const hasSepaMandate = isSepaMandateCountry();
  const isBankFiType = uiState.fiType === 'bank';

  if (hasSepaMandate && isBankFiType) {
    filteredFormState.sepaMandate = formState.sepaMandate;
  }

  const { api: apiState } = appStore.getState();
  const { hasPrefillAddress } = apiState.prefillAddressMetadata;
  const isAddressless = features.isActive('isAddressless');
  if (isAddressless) {
    // Since we aren't showing the address fields we delete the
    // billing address from the form state
    delete filteredFormState.billingAddress;

    // If we were not sent a shipping address from the merchant
    // then we delete the shipping address from the form state
    if (!hasPrefillAddress) {
      delete filteredFormState.shippingAddress;
    } else {
      // Since the shipping address fields are not displayed the user will not
      // be able to fix any errors, so we set the validity to valid
      filteredFormState.shippingAddress = getForcedValidCopy(
        filteredFormState.shippingAddress,
      );
    }

    if (filteredFormState.residentialAddress) {
      delete filteredFormState.residentialAddress;
    }

    return filteredFormState;
  }

  const isAllowChangeShipping = features.isActive('isAllowChangeShipping');
  if (!isAllowChangeShipping) {
    if (hasPrefillAddress) {
      const { shippingAddress } = filteredFormState;

      return {
        ...filteredFormState,
        shippingAddress: {
          // Since the shipping address fields are not displayed the user will
          // not be able to fix any errors, so we set the validity to valid
          ...getForcedValidCopy(shippingAddress),
          firstName: {
            value: shippingAddress.value || firstName.value,
          },
          lastName: {
            value: shippingAddress.value || lastName.value,
          },
        },
      };
    }

    return {
      ...filteredFormState,
      shippingAddress: getShippingAddressFromBillingAddress({
        billingAddress: filteredFormState.billingAddress,
        firstName,
        lastName,
      }),
    };
  }

  // If we are shipping to the billing address we need to copy its values
  // over to the shippingAddress state field.
  const { value: shipToBilling } = formState.shipToBilling;
  if (shipToBilling) {
    return {
      ...filteredFormState,
      shippingAddress: getShippingAddressFromBillingAddress({
        billingAddress: filteredFormState.billingAddress,
        firstName,
        lastName,
      }),
    };
  }

  return filteredFormState;
};

/**
 * @function triggerMemberBenefitsTrueGuestsInterstitial
 * @description Prompts the user with a True Guests Interstitial
 * @returns {Boolean}
 */
// This function is in this file to prevent a circular dependency
const triggerMemberBenefitsTrueGuestsInterstitial = (): boolean => {
  const isStreamlineOptionalExperience = features.isActive(
    'isStreamlineOptionalExperience',
  );
  const shouldShowOptionalUpsellHalfSheet = features.hasFeature(
    'shouldShowOptionalUpsellHalfSheet',
  );
  const isUserExists = appStore.getState().api.isExistingAccount;
  const isPomaButtonFlow = features.isActive('isPOMAEligible');
  const { form: formState } = appStore.getState();
  const {
    ui: {
      isMemberBenefitsTrueGuestsInterstitialOpen,
      isMemberBenefitsTrueGuestsInterstitialReject,
      fiType,
    },
  } = appStore.getState();

  const onboardOptionValue = formState.onboardOption.value;
  const filteredFormState = filterFormState(formState);
  const { formErrors } = validateForm(filteredFormState);
  const fieldsWithErrors = Object.entries(formErrors);

  const isBNPL = features.get('bnplExperience') && fiType === 'bnpl';

  if (
    (!fieldsWithErrors || !isMemberBenefitsTrueGuestsInterstitialOpen) &&
    !isMemberBenefitsTrueGuestsInterstitialReject &&
    onboardOptionValue === 'guest' &&
    shouldShowOptionalUpsellHalfSheet &&
    !isUserExists &&
    (isPomaButtonFlow || isStreamlineOptionalExperience) &&
    !isBNPL
  ) {
    return true;
  }
  return false;
};

export {
  filterFormState,
  formatInstallmentOption,
  serializeFormData,
  serializeFormDataForGuestUpgradeEligible,
  serializeOnboardingPlanData,
  triggerMemberBenefitsTrueGuestsInterstitial,
};
