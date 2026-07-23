// External libraries
import gql from 'graphql-tag';

//Internal Modules
import { BUYER_FRAGMENT } from '../fragments';

export const CREATE_MEMBER_ACCOUNT_MUTATION = gql`
  mutation CreateMemberAccountMutation(
    $billingAddress: AddressInput
    $contentIdentifier: String
    $country: CountryCodes!
    $crsData: CommonReportingStandardsInput
    $dateOfBirth: DateOfBirth
    $email: String!
    $firstName: String!
    $gender: Gender
    $identityDocument: IdentityDocumentInput
    $lastName: String!
    $marketingOptOut: Boolean
    $nationality: CountryCodes
    $occupation: Occupation
    $password: String
    $phone: PhoneInput!
    $placeOfBirth: CountryCodes
    $secondaryIdentityDocument: IdentityDocumentInput
    $shippingAddress: AddressInput
    $token: String!
    $residentialAddress: AddressInput
    $legalAgreements: LegalAgreementsInput
  ) {
    onboardAccount: createMemberAccount(
      billingAddress: $billingAddress
      contentIdentifier: $contentIdentifier
      country: $country
      crsData: $crsData
      dateOfBirth: $dateOfBirth
      email: $email
      firstName: $firstName
      gender: $gender
      identityDocument: $identityDocument
      lastName: $lastName
      marketingOptOut: $marketingOptOut
      nationality: $nationality
      occupation: $occupation
      password: $password
      phone: $phone
      placeOfBirth: $placeOfBirth
      secondaryIdentityDocument: $secondaryIdentityDocument
      shippingAddress: $shippingAddress
      token: $token
      residentialAddress: $residentialAddress
      legalAgreements: $legalAgreements
    ) {
      ...buyer
    }
  }
  ${BUYER_FRAGMENT}
`;
